import Foundation

/// The session token in `~/Library/Application Support/Share/<host>.token`, readable by the
/// user only. Not the keychain: the app is signed ad hoc, so every rebuild is a new
/// application to the keychain and it asks for the login password again.
enum TokenStore {
    private static var dir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Share", isDirectory: true)
    }

    private static func file(_ account: String) -> URL {
        dir.appendingPathComponent(account + ".token")
    }

    static func read(_ account: String) -> String? {
        (try? String(contentsOf: file(account), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func write(_ account: String, _ value: String) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        try? Data(value.utf8).write(to: file(account), options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file(account).path)
    }

    static func delete(_ account: String) {
        try? FileManager.default.removeItem(at: file(account))
    }
}
