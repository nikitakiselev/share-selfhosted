import AppKit
import SwiftUI

@main
struct ShareApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var state = AppState.shared

    var body: some Scene {
        MenuBarExtra("Share", systemImage: "arrow.up.circle") {
            PopoverView()
                .environmentObject(state)
        }
        .menuBarExtraStyle(.window)
    }
}

extension AppState {
    static let shared = AppState()
}

/// The website returns the connect code through the share-app:// scheme.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme == "share-app" {
            AppState.shared.handle(url: url)
        }
    }
}
