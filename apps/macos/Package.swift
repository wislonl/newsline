// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "Newsline",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "Newsline", targets: ["Newsline"])
    ],
    targets: [
        .executableTarget(
            name: "Newsline",
            path: "Sources/Newsline"
        )
    ]
)
