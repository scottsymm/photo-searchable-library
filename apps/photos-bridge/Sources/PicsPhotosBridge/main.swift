import Foundation
import Photos

struct BridgeOptions {
    var apiURL = URL(string: "http://localhost:8000")!
    var limit = 25
    var dryRun = false
    var watch = false
    var pollInterval: UInt64 = 5
}

struct SyncRequest: Codable {
    let id: Int
    let limit_count: Int
    let full_sync: Int
}

struct SyncResponse: Codable {
    let sync: SyncRequest?
}

struct KnownAssetsRequest: Codable {
    let source_asset_ids: [String]
}

struct KnownAssetsResponse: Codable {
    let source_asset_ids: [String]
}

struct SyncResult {
    let importedCount: Int
    let failedCount: Int
    let errors: [String]
}

func parseOptions() -> BridgeOptions {
    var options = BridgeOptions()
    var arguments = CommandLine.arguments.dropFirst()
    while let argument = arguments.popFirst() {
        switch argument {
        case "--api-url":
            if let value = arguments.popFirst(), let url = URL(string: value) {
                options.apiURL = url
            }
        case "--limit":
            if let value = arguments.popFirst(), let limit = Int(value) {
                options.limit = limit
            }
        case "--dry-run":
            options.dryRun = true
        case "--watch":
            options.watch = true
        case "--poll-interval":
            if let value = arguments.popFirst(), let interval = UInt64(value) {
                options.pollInterval = max(1, interval)
            }
        default:
            break
        }
    }
    return options
}

func apiRequest(_ path: String, method: String, body: Data? = nil, contentType: String = "application/x-www-form-urlencoded", options: BridgeOptions) async throws -> Data {
    var request = URLRequest(url: options.apiURL.appendingPathComponent(path))
    request.httpMethod = method
    request.httpBody = body
    if body != nil {
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
        throw NSError(domain: "PicsPhotosBridge", code: 2, userInfo: [NSLocalizedDescriptionKey: String(data: data, encoding: .utf8) ?? "API request failed"])
    }
    return data
}

func knownAssetIDs(_ sourceAssetIDs: [String], options: BridgeOptions) async throws -> Set<String> {
    let body = try JSONEncoder().encode(KnownAssetsRequest(source_asset_ids: sourceAssetIDs))
    let data = try await apiRequest("/sources/apple-photos/assets/known", method: "POST", body: body, contentType: "application/json", options: options)
    return Set(try JSONDecoder().decode(KnownAssetsResponse.self, from: data).source_asset_ids)
}

func claimSync(options: BridgeOptions) async throws -> SyncRequest? {
    let data = try await apiRequest("/sources/apple-photos/sync/claim", method: "POST", options: options)
    return try JSONDecoder().decode(SyncResponse.self, from: data).sync
}

func completeSync(_ sync: SyncRequest, result: SyncResult, error: String? = nil, options: BridgeOptions) async throws {
    var fields = "imported_count=\(result.importedCount)&failed_count=\(result.failedCount)"
    if let error {
        fields += "&error=\(error.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? error)"
    }
    _ = try await apiRequest("/sources/apple-photos/sync/\(sync.id)/complete", method: "POST", body: fields.data(using: .utf8), options: options)
}

func authorizationName(_ status: PHAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "notDetermined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .authorized: return "authorized"
    case .limited: return "limited"
    @unknown default: return "unknown"
    }
}

func requestAccess() async -> PHAuthorizationStatus {
    let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    if current != .notDetermined { return current }
    return await PHPhotoLibrary.requestAuthorization(for: .readWrite)
}

func primaryResource(for asset: PHAsset) -> PHAssetResource? {
    let resources = PHAssetResource.assetResources(for: asset)
    if asset.mediaType == .video {
        return resources.first { $0.uniformTypeIdentifier.contains("movie") || $0.uniformTypeIdentifier.contains("video") } ?? resources.first
    }
    return resources.first { $0.uniformTypeIdentifier.contains("image") || $0.uniformTypeIdentifier.contains("jpeg") || $0.uniformTypeIdentifier.contains("heic") } ?? resources.first
}

func extract(resource: PHAssetResource, to output: URL) async throws {
    if FileManager.default.fileExists(atPath: output.path) {
        try FileManager.default.removeItem(at: output)
    }
    let options = PHAssetResourceRequestOptions()
    options.isNetworkAccessAllowed = true
    try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
        PHAssetResourceManager.default().writeData(for: resource, toFile: output, options: options) { error in
            if let error {
                continuation.resume(throwing: error)
            } else {
                continuation.resume(returning: ())
            }
        }
    }
}

func upload(asset: PHAsset, resource: PHAssetResource, fileURL: URL, assetCount: Int, options: BridgeOptions) async throws {
    var request = URLRequest(url: options.apiURL.appendingPathComponent("/sources/apple-photos/assets"))
    request.httpMethod = "POST"
    let boundary = UUID().uuidString
    request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

    var body = Data()
    func field(_ name: String, _ value: String) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(value)\r\n".data(using: .utf8)!)
    }

    field("source_asset_id", asset.localIdentifier)
    field("original_filename", resource.originalFilename)
    field("media_type", asset.mediaType == .video ? "video" : "image")
    field("asset_count", String(assetCount))
    if let creationDate = asset.creationDate {
        field("taken_at", creationDate.ISO8601Format())
    }
    field("authorization_state", authorizationName(PHPhotoLibrary.authorizationStatus(for: .readWrite)))

    let filename = resource.originalFilename
    let mime = asset.mediaType == .video ? "video/quicktime" : "application/octet-stream"
    body.append("--\(boundary)\r\n".data(using: .utf8)!)
    body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
    body.append("Content-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
    body.append(try Data(contentsOf: fileURL))
    body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

    let (data, response) = try await URLSession.shared.upload(for: request, from: body)
    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
        throw NSError(domain: "PicsPhotosBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: String(data: data, encoding: .utf8) ?? "upload failed"])
    }
}

func syncAssets(options: BridgeOptions, limit: Int, fullSync: Bool = false) async throws -> SyncResult {
    let fetchOptions = PHFetchOptions()
    fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
    let assets = PHAsset.fetchAssets(with: fetchOptions)
    print("asset_count=\(assets.count)")

    let count = min(limit, assets.count)
    var assetsToImport: [PHAsset] = []
    if fullSync {
        let chunkSize = 500
        for start in stride(from: 0, to: assets.count, by: chunkSize) {
            let end = min(start + chunkSize, assets.count)
            let candidates = (start..<end).map { assets.object(at: $0) }
            let known = try await knownAssetIDs(candidates.map(\.localIdentifier), options: options)
            assetsToImport.append(contentsOf: candidates.filter { !known.contains($0.localIdentifier) })
        }
        print("assets_to_import=\(assetsToImport.count)")
    } else {
        assetsToImport = (0..<count).map { assets.object(at: $0) }
    }
    let temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try? FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: temporaryDirectory) }
    var importedCount = 0
    var failedCount = 0
    var errors: [String] = []

    for asset in assetsToImport {
        guard let resource = primaryResource(for: asset) else {
            print("skip=\(asset.localIdentifier) reason=no-resource")
            failedCount += 1
            errors.append("\(asset.localIdentifier): no primary resource")
            continue
        }
        print("asset=\(asset.localIdentifier) file=\(resource.originalFilename)")
        if options.dryRun { continue }
        let output = temporaryDirectory.appendingPathComponent(resource.originalFilename)
        do {
            defer { try? FileManager.default.removeItem(at: output) }
            try await extract(resource: resource, to: output)
            try await upload(asset: asset, resource: resource, fileURL: output, assetCount: assets.count, options: options)
            importedCount += 1
            print("uploaded=\(asset.localIdentifier)")
        } catch {
            print("error=\(asset.localIdentifier) \(error.localizedDescription)")
            failedCount += 1
            errors.append("\(asset.localIdentifier): \(error.localizedDescription)")
        }
    }
    return SyncResult(importedCount: importedCount, failedCount: failedCount, errors: errors)
}

@main
struct PicsPhotosBridge {
    static func main() async {
        let options = parseOptions()
        let status = await requestAccess()
        print("authorization=\(authorizationName(status))")
        guard status == .authorized || status == .limited else {
            exit(2)
        }

        if options.watch {
            print("watching_for_sync_requests=true")
            while true {
                do {
                    if let sync = try await claimSync(options: options) {
                        print("sync_started=\(sync.id) limit=\(sync.limit_count)")
                        do {
                            let result = try await syncAssets(options: options, limit: sync.limit_count, fullSync: sync.full_sync == 1)
                            let error = result.failedCount > 0 ? result.errors.prefix(10).joined(separator: "; ") : nil
                            try await completeSync(sync, result: result, error: error, options: options)
                            print("sync_completed=\(sync.id) imported=\(result.importedCount) failed=\(result.failedCount)")
                        } catch {
                            let result = SyncResult(importedCount: 0, failedCount: 1, errors: [error.localizedDescription])
                            try? await completeSync(sync, result: result, error: error.localizedDescription, options: options)
                            print("sync_error=\(sync.id) \(error.localizedDescription)")
                        }
                    }
                } catch {
                    print("sync_error=\(error.localizedDescription)")
                }
                try? await Task.sleep(for: .seconds(options.pollInterval))
            }
        }
        do {
            let result = try await syncAssets(options: options, limit: options.limit)
            if result.failedCount > 0 {
                print("sync_failed imported=\(result.importedCount) failed=\(result.failedCount)")
                exit(1)
            }
        } catch {
            print("sync_error=\(error.localizedDescription)")
            exit(1)
        }
    }
}
