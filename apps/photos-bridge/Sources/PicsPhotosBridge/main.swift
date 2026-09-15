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
}

struct SyncResponse: Codable {
    let sync: SyncRequest?
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

func apiRequest(_ path: String, method: String, body: Data? = nil, options: BridgeOptions) async throws -> Data {
    var request = URLRequest(url: options.apiURL.appendingPathComponent(path))
    request.httpMethod = method
    request.httpBody = body
    if body != nil {
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
        throw NSError(domain: "PicsPhotosBridge", code: 2, userInfo: [NSLocalizedDescriptionKey: String(data: data, encoding: .utf8) ?? "API request failed"])
    }
    return data
}

func claimSync(options: BridgeOptions) async throws -> SyncRequest? {
    let data = try await apiRequest("/sources/apple-photos/sync/claim", method: "POST", options: options)
    return try JSONDecoder().decode(SyncResponse.self, from: data).sync
}

func completeSync(_ sync: SyncRequest, importedCount: Int, error: String? = nil, options: BridgeOptions) async throws {
    var fields = "imported_count=\(importedCount)"
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

func syncAssets(options: BridgeOptions, limit: Int) async throws -> Int {
    let fetchOptions = PHFetchOptions()
    fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
    let assets = PHAsset.fetchAssets(with: fetchOptions)
    print("asset_count=\(assets.count)")

    let count = min(limit, assets.count)
    let temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try? FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    var importedCount = 0

    for index in 0..<count {
        let asset = assets.object(at: index)
        guard let resource = primaryResource(for: asset) else {
            print("skip=\(asset.localIdentifier) reason=no-resource")
            continue
        }
        print("asset=\(asset.localIdentifier) file=\(resource.originalFilename)")
        if options.dryRun { continue }
        let output = temporaryDirectory.appendingPathComponent(resource.originalFilename)
        do {
            try await extract(resource: resource, to: output)
            try await upload(asset: asset, resource: resource, fileURL: output, assetCount: assets.count, options: options)
            importedCount += 1
            print("uploaded=\(asset.localIdentifier)")
        } catch {
            print("error=\(asset.localIdentifier) \(error.localizedDescription)")
        }
    }
    return importedCount
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
                        let importedCount = try await syncAssets(options: options, limit: sync.limit_count)
                        try await completeSync(sync, importedCount: importedCount, options: options)
                        print("sync_completed=\(sync.id) imported=\(importedCount)")
                    }
                } catch {
                    print("sync_error=\(error.localizedDescription)")
                }
                try? await Task.sleep(for: .seconds(options.pollInterval))
            }
        }
        _ = try? await syncAssets(options: options, limit: options.limit)
    }
}
