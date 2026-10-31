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
        .testTarget(name: "ShareAppTests", dependencies: ["ShareApp"], path: "Tests/ShareAppTests"),
    ]
)
