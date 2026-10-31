import Foundation

/// tus 1.0.0 client: creation, then PATCH in chunks; after a dropped connection the offset is
/// re-read with HEAD and the upload continues from where the server left off.
struct TusUploader {
    static let chunk = 4 << 20
    static let retries = 5

    let api: ApiClient
    let slug: String

    private var tusHeaders: [String: String] { ["Tus-Resumable": "1.0.0"] }

    private func metadata(_ pairs: [String: String]) -> String {
        pairs.map { "\($0.key) \(Data($0.value.utf8).base64EncodedString())" }.joined(separator: ",")
    }

    func upload(file: URL, progress: @escaping (Int64) -> Void) async throws {
        let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
        let size = (attrs[.size] as? NSNumber)?.int64Value ?? 0
        let modified = (attrs[.modificationDate] as? Date).map { String(Int($0.timeIntervalSince1970 * 1000)) }
        var meta = ["share": slug, "filename": file.lastPathComponent, "filetype": mimeType(of: file)]
        if let modified { meta["lastmodified"] = modified }

        let create = api.request("POST", "api/app/tus/", headers: tusHeaders.merging(
            ["Upload-Length": String(size), "Upload-Metadata": metadata(meta)]) { $1 })
        let (_, resp) = try await api.send(create)
        guard let location = resp.value(forHTTPHeaderField: "Location") else {
            throw ApiError(status: 500, code: "no_location", message: "tus: Location header missing")
        }
        let path = location.hasPrefix("/") ? String(location.dropFirst()) : location

        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var offset: Int64 = 0
        var attempt = 0
        while offset < size {
            try Task.checkCancellation()
            try handle.seek(toOffset: UInt64(offset))
            let data = handle.readData(ofLength: Self.chunk)
            if data.isEmpty { break }
            var req = api.request("PATCH", path, headers: tusHeaders.merging(
                ["Upload-Offset": String(offset), "Content-Type": "application/offset+octet-stream"]) { $1 })
            req.timeoutInterval = 300
            do {
                let (_, r) = try await api.send(req, from: data)
                offset = Int64(r.value(forHTTPHeaderField: "Upload-Offset") ?? "") ?? offset + Int64(data.count)
                attempt = 0
            } catch let e as ApiError where e.status != 409 {
                throw e
            } catch {
                // network hiccup or an offset mismatch: ask the server where it is
                attempt += 1
                if attempt > Self.retries { throw error }
                try await Task.sleep(nanoseconds: UInt64(attempt) * 1_000_000_000)
                let head = api.request("HEAD", path, headers: tusHeaders)
                if let (_, r) = try? await api.send(head), let o = Int64(r.value(forHTTPHeaderField: "Upload-Offset") ?? "") {
                    offset = o
                }
            }
            progress(offset)
        }
    }

    private func mimeType(of url: URL) -> String {
        (try? url.resourceValues(forKeys: [.contentTypeKey]).contentType?.preferredMIMEType)
            .flatMap { $0 } ?? "application/octet-stream"
    }
}
