import AppKit
import Foundation
import Vision

struct OCRItem: Codable {
    let text: String
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: macos_vision_ocr.swift IMAGE\n".utf8))
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL) else {
    FileHandle.standardError.write(Data("cannot load image\n".utf8))
    exit(3)
}
var proposedRect = NSRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
    FileHandle.standardError.write(Data("cannot create CGImage\n".utf8))
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
// The rank-segment parser only needs numeric columns. en-US is available offline
// on minimal Command Line Tools installations; zh-Hans may trigger a model download.
request.recognitionLanguages = ["en-US"]
request.usesLanguageCorrection = false
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try handler.perform([request])

let items: [OCRItem] = (request.results ?? []).compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return OCRItem(
        text: candidate.string,
        x: box.origin.x,
        y: box.origin.y,
        width: box.size.width,
        height: box.size.height
    )
}
let encoder = JSONEncoder()
let data = try encoder.encode(items)
FileHandle.standardOutput.write(data)
