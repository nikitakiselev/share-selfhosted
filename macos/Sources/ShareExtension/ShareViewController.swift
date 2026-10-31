import AppKit
import UniformTypeIdentifiers

/// "Copy link with Share" in the Finder share menu. No interface of its own: it hands the
/// files to the menu bar app through its URL scheme and finishes at once. The app uploads
/// them to a one-hour link and copies the link.
final class ShareViewController: NSViewController {
    override func loadView() {
        view = NSView(frame: .zero)
    }

    override func viewDidAppear() {
        super.viewDidAppear()
        Task { await forward() }
    }

    private func forward() async {
        var paths: [String] = []
        for item in extensionContext?.inputItems as? [NSExtensionItem] ?? [] {
            for provider in item.attachments ?? [] where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                if let url = await provider.fileURL() { paths.append(url.path) }
            }
        }
        if !paths.isEmpty {
            var c = URLComponents()
            c.scheme = "share-app"
            c.host = "upload"
            c.queryItems = [URLQueryItem(name: "expires", value: "3600")] + paths.map { URLQueryItem(name: "path", value: $0) }
            if let url = c.url { NSWorkspace.shared.open(url) }
        }
        extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
    }
}

extension NSItemProvider {
    func fileURL() async -> URL? {
        await withCheckedContinuation { cont in
            loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) {
                    cont.resume(returning: url)
                } else if let url = item as? URL {
                    cont.resume(returning: url)
                } else {
                    cont.resume(returning: nil)
                }
            }
        }
    }
}
