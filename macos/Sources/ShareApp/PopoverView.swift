import SwiftUI
import UniformTypeIdentifiers

private let cardRadius: CGFloat = 14

struct PopoverView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        Group {
            switch state.phase {
            case .checking:
                ProgressView().controlSize(.small)
            case .offline(let text):
                VStack(spacing: 14) {
                    Text(text).foregroundStyle(.secondary)
                    Button(L10n.retry) { Task { await state.refresh() } }
                }
            case .signedOut(let waiting):
                SignedOutView(waiting: waiting)
            case .ready, .uploading, .finished:
                SignedInView()
            }
        }
        // one size for every state: the MenuBarExtra window does not shrink when the content does
        .frame(width: 320, height: 300)
        .onAppear { Task { await state.refresh() } }
    }
}

private struct SignedOutView: View {
    @EnvironmentObject private var state: AppState
    let waiting: Bool

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            Image(systemName: "arrow.up.circle.fill")
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(.tint)
            Text(L10n.welcome)
                .font(.system(.title2, design: .rounded, weight: .semibold))
                .padding(.top, 14)
            Text(L10n.pleaseSignIn)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 6)
            if let error = state.error {
                Text(error).font(.caption).foregroundStyle(.red).multilineTextAlignment(.center).padding(.top, 8)
            }
            Group {
                if waiting {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(L10n.waitingForBrowser).font(.callout).foregroundStyle(.secondary)
                        Button(L10n.cancel) { state.cancelSignIn() }.buttonStyle(.link).font(.callout)
                    }
                } else {
                    Button(L10n.signIn) { state.beginSignIn() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .keyboardShortcut(.defaultAction)
                }
            }
            .frame(height: 36)
            .padding(.top, 22)
            Spacer()
            HStack { Spacer(); QuitButton() }
        }
        .padding(20)
    }
}

private struct SignedInView: View {
    @EnvironmentObject private var state: AppState
    @State private var targeted = false

    var body: some View {
        VStack(spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(state.user?.email ?? state.user?.login ?? "")
                    .font(.callout).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
                Spacer()
                Button(L10n.signOut) { state.signOut() }.buttonStyle(.link).font(.callout)
            }

            Group {
                switch state.phase {
                case .uploading(let index, let total, let name, let done, let size):
                    UploadingView(index: index, total: total, name: name, done: done, size: size)
                case .finished(let url):
                    FinishedView(url: url)
                default:
                    dropZone
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: cardRadius).fill(.quaternary.opacity(0.5)))

            if let error = state.error {
                Text(error).font(.caption).foregroundStyle(.red).multilineTextAlignment(.center).lineLimit(2)
            }

            HStack {
                Text(state.usageLine).font(.caption).foregroundStyle(.secondary)
                Spacer()
                QuitButton()
            }
        }
        .padding(16)
    }

    private var dropZone: some View {
        VStack(spacing: 8) {
            Image(systemName: "plus")
                .font(.system(size: 26, weight: .light))
                .foregroundStyle(targeted ? AnyShapeStyle(.tint) : AnyShapeStyle(.secondary))
            Text(L10n.dropHere).font(.callout.weight(.medium))
            Text(L10n.orClick).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .overlay(
            RoundedRectangle(cornerRadius: cardRadius)
                .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 5]))
                .foregroundStyle(.tint)
                .opacity(targeted ? 1 : 0)
        )
        .contentShape(RoundedRectangle(cornerRadius: cardRadius))
        .onTapGesture { state.chooseFiles() }
        .onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
            Task {
                var urls: [URL] = []
                for p in providers {
                    if let url = await p.fileURL() { urls.append(url) }
                }
                state.upload(urls)
            }
            return true
        }
        .animation(.easeOut(duration: 0.15), value: targeted)
    }
}

private struct UploadingView: View {
    @EnvironmentObject private var state: AppState
    let index: Int, total: Int, name: String, done: Int64, size: Int64

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Spacer()
            Text(name).font(.callout.weight(.medium)).lineLimit(1).truncationMode(.middle)
            ProgressView(value: size > 0 ? Double(done) / Double(size) : 0)
            HStack {
                Text(size > 0 ? "\(L10n.size(done)) / \(L10n.size(size))" : L10n.uploading)
                if total > 1 { Text("· \(L10n.fileOf(index, total))") }
                Spacer()
                Button(L10n.cancel) { state.cancelUpload() }.buttonStyle(.link)
            }
            .font(.caption).foregroundStyle(.secondary).monospacedDigit()
            Spacer()
        }
        .padding(.horizontal, 18)
    }
}

private struct FinishedView: View {
    @EnvironmentObject private var state: AppState
    let url: String

    var body: some View {
        VStack(spacing: 10) {
            Spacer()
            Label(L10n.linkReady, systemImage: "checkmark.circle.fill")
                .font(.callout.weight(.medium))
                .foregroundStyle(.green)
            Text(url)
                .font(.callout.monospaced())
                .textSelection(.enabled)
                .lineLimit(1).truncationMode(.middle)
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 7).fill(.background.opacity(0.7)))
            HStack(spacing: 10) {
                Button(state.copied ? L10n.copied : L10n.copy) { state.copyLink(url) }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                Button(L10n.newUpload) { state.reset() }.buttonStyle(.link)
            }
            .padding(.top, 4)
            Spacer()
        }
        .padding(.horizontal, 18)
    }
}

/// Quits the app itself (sign out only ends the session). Small and quiet: it is needed rarely.
private struct QuitButton: View {
    var body: some View {
        Button { NSApp.terminate(nil) } label: {
            Image(systemName: "power").font(.caption)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.tertiary)
        .help(L10n.quit)
        .keyboardShortcut("q")
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
