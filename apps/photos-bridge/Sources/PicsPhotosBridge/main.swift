import Foundation
import Photos

struct BridgeOptions {
    var apiURL = URL(string: "http://localhost:8000")!
    var limit = 25
    var dryRun = false
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
        default:
            break
        }
    }
    return options
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

func upload(asset: PHAsset, resource: PHAssetResource, fileURL: URL, options: BridgeOptions) async throws {
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

@main
struct PicsPhotosBridge {
    static func main() async {
        let options = parseOptions()
        let status = await requestAccess()
        print("authorization=\(authorizationName(status))")
        guard status == .authorized || status == .limited else {
            exit(2)
        }

        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        let assets = PHAsset.fetchAssets(with: fetchOptions)
        print("asset_count=\(assets.count)")

        let count = min(options.limit, assets.count)
        let temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try? FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)

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
                try await upload(asset: asset, resource: resource, fileURL: output, options: options)
                print("uploaded=\(asset.localIdentifier)")
            } catch {
                print("error=\(asset.localIdentifier) \(error.localizedDescription)")
            }
        }
    }
}
