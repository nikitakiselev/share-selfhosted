import Foundation

/// Folders are uploaded as zip archives made on the Mac with `ditto` (the same format as
/// Finder's "Compress"): the server stores files only.
enum Packer {
    static func isDirectory(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    /// Bytes of all regular files under the folder.
    static func totalSize(_ folder: URL) -> Int64 {
        var total: Int64 = 0
        let keys: [URLResourceKey] = [.isRegularFileKey, .fileSizeKey]
        if let e = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: keys, options: []) {
            for case let url as URL in e {
                if let v = try? url.resourceValues(forKeys: Set(keys)), v.isRegularFile == true {
                    total += Int64(v.fileSize ?? 0)
                }
            }
        }
        return total
    }

    /// `<tmp>/<uuid>/<name>.zip` for a folder; the caller removes the parent directory after the upload.
    /// ditto reports nothing, so `progress` gets the growing size of the archive against the
    /// folder size — exact for media and other incompressible data, short of the end otherwise.
    static func zip(_ folder: URL, progress: @escaping (Int64) -> Void) async throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let out = dir.appendingPathComponent(folder.lastPathComponent + ".zip")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = ["-c", "-k", "--sequesterRsrc", "--keepParent", folder.path, out.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        let poll = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 250_000_000)
                if let size = (try? FileManager.default.attributesOfItem(atPath: out.path))?[.size] as? Int64 {
                    progress(size)
                }
            }
        }
        defer { poll.cancel() }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
                process.terminationHandler = { p in
                    if p.terminationStatus == 0 {
                        cont.resume()
                    } else {
                        cont.resume(throwing: ApiError(status: 0, code: "zip_failed",
                                                       message: "ditto exited with \(p.terminationStatus)"))
                    }
                }
                do { try process.run() } catch { cont.resume(throwing: error) }
            }
        } onCancel: {
            process.terminate()
        }
        try Task.checkCancellation()
        return out
    }
}
