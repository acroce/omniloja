import Foundation
import Vision
import ImageIO
import CoreGraphics

guard CommandLine.arguments.count == 2 else {
  fputs("Uso: ocr-comprovante.swift <imagem>\n", stderr)
  exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])

func renderPdfFirstPage(_ url: URL) -> CGImage? {
  guard let document = CGPDFDocument(url as CFURL),
        let page = document.page(at: 1) else {
    return nil
  }

  let pageRect = page.getBoxRect(.mediaBox)
  let scale = 2.0
  let width = Int(pageRect.width * scale)
  let height = Int(pageRect.height * scale)
  guard width > 0, height > 0,
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let context = CGContext(
          data: nil,
          width: width,
          height: height,
          bitsPerComponent: 8,
          bytesPerRow: 0,
          space: colorSpace,
          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
    return nil
  }

  context.setFillColor(CGColor.white)
  context.fill(CGRect(x: 0, y: 0, width: width, height: height))
  context.translateBy(x: 0, y: CGFloat(height))
  context.scaleBy(x: CGFloat(scale), y: -CGFloat(scale))
  context.drawPDFPage(page)
  return context.makeImage()
}

let imageSource = CGImageSourceCreateWithURL(imageURL as CFURL, nil)
let imageFromImageSource = imageSource.flatMap { CGImageSourceCreateImageAtIndex($0, 0, nil) }
let imageFromPdf = imageURL.pathExtension.lowercased() == "pdf" ? renderPdfFirstPage(imageURL) : nil

guard let image = imageFromImageSource ?? imageFromPdf else {
  fputs("Imagem invalida ou nao suportada.\n", stderr)
  exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
let preferredLanguages = ["pt-BR", "en-US"]
if let supportedLanguages = try? request.supportedRecognitionLanguages() {
  let available = preferredLanguages.filter { supportedLanguages.contains($0) }
  if !available.isEmpty {
    request.recognitionLanguages = available
  }
} else {
  request.recognitionLanguages = preferredLanguages
}

do {
  try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
} catch {
  fputs("OCR falhou: \(error.localizedDescription)\n", stderr)
  exit(1)
}

for observation in request.results ?? [] {
  if let text = observation.topCandidates(1).first?.string {
    print(text)
  }
}
