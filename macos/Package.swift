// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "ShareApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "ShareApp",
            path: "Sources/ShareApp",
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        ),
        // The Finder "Share" menu item. An app extension is an executable whose entry point is
        // NSExtensionMain; build.sh packs it into Share.app/Contents/PlugIns.
        .executableTarget(
            name: "ShareExtension",
            path: "Sources/ShareExtension",
            swiftSettings: [.unsafeFlags(["-parse-as-library", "-application-extension"])],
            linkerSettings: [.unsafeFlags(["-Xlinker", "-e", "-Xlinker", "_NSExtensionMain"])]
        ),
        .testTarget(name: "ShareAppTests", dependencies: ["ShareApp"], path: "Tests/ShareAppTests"),
    ]
)
