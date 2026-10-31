import AppKit
import SwiftUI

// No SwiftUI App scene: the status item and its popover are made by hand in AppDelegate.
// MenuBarExtra cannot be opened from code, and uploads started from Finder have to bring the
// window up; a placeholder Settings scene would open an empty window on activation.
@main
enum Main {
    static let delegate = AppDelegate()

    static func main() {
        let app = NSApplication.shared
        app.delegate = delegate
        app.run()
    }
}

extension AppState {
    static let shared = AppState()
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let popover = NSPopover()

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            button.image = Self.menuBarIcon()
            button.target = self
            button.action = #selector(toggle)
        }
        popover.contentSize = NSSize(width: 320, height: 300)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: PopoverView().environmentObject(AppState.shared))
        AppState.shared.showPopover = { [weak self] in self?.show() }
    }

    /// Icons/MenuBarIcon.svg from the bundle as a template image (tinted by the system like the
    /// built-in status items); the SF Symbol is the fallback for a bare `swift run`.
    static func menuBarIcon() -> NSImage? {
        if let url = Bundle.main.url(forResource: "MenuBarIcon", withExtension: "svg"), let image = NSImage(contentsOf: url) {
            image.size = NSSize(width: 18, height: 18)
            image.isTemplate = true
            return image
        }
        return NSImage(systemSymbolName: "arrow.up.circle", accessibilityDescription: "Share")
    }

    /// The website returns the connect code, the share extension sends files — share-app://…
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme == "share-app" {
            AppState.shared.handle(url: url)
        }
    }

    @objc private func toggle() {
        popover.isShown ? popover.performClose(nil) : show()
    }

    private func show() {
        guard let button = statusItem.button, !popover.isShown else { return }
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }
}
