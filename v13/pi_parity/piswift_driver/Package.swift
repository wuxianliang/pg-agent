// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "piswift_driver",
    platforms: [.macOS(.v15)],
    dependencies: [
        .package(path: "/Users/wxl/Projects/PiSwift"),
    ],
    targets: [
        .executableTarget(
            name: "piswift_driver",
            dependencies: [
                .product(name: "PiSwiftCodingAgent", package: "PiSwift"),
                .product(name: "PiSwiftAgent", package: "PiSwift"),
                .product(name: "PiSwiftAI", package: "PiSwift"),
            ]
        ),
    ]
)
