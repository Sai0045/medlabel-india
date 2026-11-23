import Foundation
import Vision
import AppKit

// Local Apple Vision, no network service. Output engine observations, not medical confidence.
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
request.usesLanguageCorrection = false
let bytes = FileHandle.standardInput.readDataToEndOfFile()
do {
    let handler = VNImageRequestHandler(data: bytes)
    try handler.perform([request])
    let rows: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let r = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "bbox": [r.minX, r.minY, r.width, r.height]]
    }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: rows))
} catch {
    FileHandle.standardError.write(Data("Local OCR failed: \(error)\n".utf8)); exit(1)
}
