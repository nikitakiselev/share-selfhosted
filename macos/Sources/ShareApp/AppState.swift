import AppKit
import Foundation

enum Phase: Equatable {
    case checking
    case offline(String)
    case signedOut(waiting: Bool)
    case ready
    case uploading(index: Int, total: Int, name: String, done: Int64, size: Int64)
    case finished(url: String, names: [String], expires: Bool)
}

@MainActor
final class AppState: ObservableObject {
    static let defaultServer = "https://share.nikitakiselev.com"
    static let serverKey = "serverURL"

    @Published var phase: Phase = .checking
    @Published var user: User?
    @Published var error: String?
    @Published var copied = false
    /// Set by the status bar controller: brings the popover up (uploads started from Finder).
    var showPopover: (() -> Void)?

    let api: ApiClient
    private let serverHost: String
    private var pkce: Pkce?
    private var uploadTask: Task<Void, Never>?

    init() {
        let raw = UserDefaults.standard.string(forKey: Self.serverKey) ?? Self.defaultServer
        let url = URL(string: raw) ?? URL(string: Self.defaultServer)!
        serverHost = url.host ?? "share"
        api = ApiClient(baseURL: url, token: TokenStore.read(url.host ?? "share"))
        Task { await refresh() }
    }

    // --- session ---

    func refresh() async {
        guard api.token != nil else {
            phase = .signedOut(waiting: pkce != nil)
            return
        }
        do {
            let info = try await api.session()
            if info.authenticated, let u = info.user {
                user = u
                if case .checking = phase { phase = .ready }
                if case .offline = phase { phase = .ready }
            } else {
                forget()
            }
        } catch let e as ApiError where e.status == 401 || e.status == 403 {
            forget()
        } catch {
            if case .checking = phase { phase = .offline(L10n.offline) }
        }
    }

    func beginSignIn() {
        let p = Pkce()
        pkce = p
        phase = .signedOut(waiting: true)
        NSWorkspace.shared.open(api.connectURL(challenge: p.challenge))
    }

    func cancelSignIn() {
        pkce = nil
        phase = .signedOut(waiting: false)
    }

    /// share-app://connect?code=… from the website, share-app://upload?path=…&expires=… from the
    /// Finder share extension.
    func handle(url: URL) {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        switch url.host {
        case "upload":
            let files = items.filter { $0.name == "path" }.compactMap { $0.value }.map { URL(fileURLWithPath: $0) }
            let expires = items.first { $0.name == "expires" }?.value.flatMap(TimeInterval.init)
            showPopover?()
            if api.token == nil {
                error = L10n.pleaseSignIn
            } else {
                upload(files, expiresIn: expires, autoCopy: true)
            }
        case "connect":
            connect(code: items.first { $0.name == "code" }?.value)
        default:
            break
        }
    }

    private func connect(code: String?) {
        guard let code, let p = pkce else { return }
        pkce = nil
        Task {
            do {
                let r = try await api.exchange(code: code, verifier: p.verifier)
                api.token = r.token
                TokenStore.write(serverHost, r.token)
                user = r.user
                error = nil
                phase = .ready
            } catch {
                self.error = error.localizedDescription
                phase = .signedOut(waiting: false)
            }
        }
    }

    func signOut() {
        let client = api
        Task { try? await client.logout() }
        forget()
    }

    private func forget() {
        api.token = nil
        TokenStore.delete(serverHost)
        user = nil
        phase = .signedOut(waiting: false)
    }

    // --- uploads ---

    /// A folder, or several items, go into one zip made on the Mac; a single file goes as is.
    /// `expiresIn` — seconds until the link dies (nil — never); `autoCopy` — put the link on
    /// the pasteboard as soon as it is ready.
    func upload(_ files: [URL], expiresIn: TimeInterval? = nil, autoCopy: Bool = false) {
        let files = files.filter {
            (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true || Packer.isDirectory($0)
        }
        guard !files.isEmpty, uploadTask == nil else { return }
        error = nil
        copied = false
        phase = .uploading(index: 1, total: files.count, name: L10n.creatingLink, done: 0, size: 0)
        uploadTask = Task { [api] in
            var slug: String?
            var temp: [URL] = []
            defer { for t in temp { try? FileManager.default.removeItem(at: t.deletingLastPathComponent()) } }
            do {
                // the zip is made first; the link is created after, so a slow zip does not eat
                // into its lifetime
                var files = files
                if files.count > 1 || Packer.isDirectory(files[0]) {
                    let name = Packer.archiveName(files)
                    let label = L10n.packing(name)
                    let total = Packer.totalSize(files)
                    phase = .uploading(index: 1, total: 1, name: label, done: 0, size: total)
                    let zip = try await Packer.zip(files, name: name) { done in
                        Task { @MainActor in
                            self.phase = .uploading(index: 1, total: 1, name: label, done: min(done, total), size: total)
                        }
                    }
                    temp.append(zip)
                    files = [zip]
                }
                phase = .uploading(index: 1, total: files.count, name: L10n.creatingLink, done: 0, size: 0)
                let expiresAt = expiresIn.map { Int(Date().addingTimeInterval($0).timeIntervalSince1970) }
                let share = try await api.createShare(expiresAt: expiresAt)
                slug = share.slug
                let tus = TusUploader(api: api, slug: share.slug)
                for (i, file) in files.enumerated() {
                    let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize).map(Int64.init) ?? 0
                    let name = file.lastPathComponent
                    phase = .uploading(index: i + 1, total: files.count, name: name, done: 0, size: size)
                    try await tus.upload(file: file) { done in
                        Task { @MainActor in
                            self.phase = .uploading(index: i + 1, total: files.count, name: name, done: done, size: size)
                        }
                    }
                }
                phase = .finished(url: share.url, names: files.map(\.lastPathComponent), expires: expiresIn != nil)
                if autoCopy { copyLink(share.url) }
            } catch is CancellationError {
                if let slug { try? await api.deleteShare(slug) }
                phase = .ready
            } catch {
                if let slug { try? await api.deleteShare(slug) }
                self.error = error.localizedDescription
                phase = .ready
            }
            uploadTask = nil
            await refresh()
        }
    }

    func cancelUpload() {
        uploadTask?.cancel()
    }

    func reset() {
        copied = false
        phase = .ready
    }

    func copyLink(_ url: String) {
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(url, forType: .string)
        copied = true
    }

    func chooseFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        NSApp.activate(ignoringOtherApps: true)
        if panel.runModal() == .OK { upload(panel.urls) }
    }

    // --- display ---

    var usageLine: String {
        guard let u = user else { return "" }
        guard let quota = u.quota else { return L10n.used(L10n.size(u.used)) }
        return L10n.free(L10n.size(max(0, quota - u.used)), of: L10n.size(quota))
    }
}
