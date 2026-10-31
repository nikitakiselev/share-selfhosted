import Foundation

/// Folders are uploaded as zip archives made on the Mac with `ditto` (the same format as
/// Finder's "Compress"): the server stores files only.
enum Packer {
    static func isDirectory(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    /// `<tmp>/<uuid>/<name>.zip` for a folder; the caller removes the parent directory after the upload.
    static func zip(_ folder: URL) async throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let out = dir.appendingPathComponent(folder.lastPathComponent + ".zip")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = ["-c", "-k", "--sequesterRsrc", "--keepParent", folder.path, out.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
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
