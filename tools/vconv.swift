// 動画を H.264・短辺最大720px・指定ビットレート・fast-start の mp4 に変換する（音声なし：LPではミュート再生のため）
// 使い方: vconv <入力> <出力.mp4> [kbps=1600]
//         vconv --poster <入力> <出力.jpg>   （最初のコマを画像に）
import AVFoundation
import ImageIO
import UniformTypeIdentifiers

if CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--poster" {
  let a = CommandLine.arguments
  let gen = AVAssetImageGenerator(asset: AVURLAsset(url: URL(fileURLWithPath: a[2])))
  gen.appliesPreferredTrackTransform = true
  gen.requestedTimeToleranceBefore = .zero
  gen.requestedTimeToleranceAfter = .zero
  let sem = DispatchSemaphore(value: 0)
  var ok = false
  gen.generateCGImageAsynchronously(for: .zero) { img, _, _ in
    if let img, let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: a[3]) as CFURL, UTType.jpeg.identifier as CFString, 1, nil) {
      CGImageDestinationAddImage(d, img, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
      ok = CGImageDestinationFinalize(d)
    }
    sem.signal()
  }
  sem.wait()
  exit(ok ? 0 : 1)
}

let a = CommandLine.arguments
guard a.count >= 3 else { print("usage: vconv in out [kbps]"); exit(2) }
let kbps = a.count > 3 ? Int(a[3]) ?? 1600 : 1600
let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
let outURL = URL(fileURLWithPath: a[2])
try? FileManager.default.removeItem(at: outURL)

let sem = DispatchSemaphore(value: 0)
var code: Int32 = 0
Task {
  do {
    guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw NSError(domain: "no video", code: 1) }
    let (natural, transform, fps) = try await track.load(.naturalSize, .preferredTransform, .nominalFrameRate)
    let short = min(natural.width, natural.height)
    let scale = min(1, 720 / short)
    func even(_ v: CGFloat) -> Int { Int((v * scale / 2).rounded()) * 2 }
    let w = even(natural.width), h = even(natural.height)

    let reader = try AVAssetReader(asset: asset)
    let rout = AVAssetReaderTrackOutput(track: track, outputSettings: [
      kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
    reader.add(rout)

    let writer = try AVAssetWriter(outputURL: outURL, fileType: .mp4)
    writer.shouldOptimizeForNetworkUse = true
    let win = AVAssetWriterInput(mediaType: .video, outputSettings: [
      AVVideoCodecKey: AVVideoCodecType.h264,
      AVVideoWidthKey: w, AVVideoHeightKey: h,
      AVVideoScalingModeKey: AVVideoScalingModeResizeAspectFill,
      AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: kbps * 1000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(max(fps, 24)),
        AVVideoExpectedSourceFrameRateKey: Int(max(fps, 24)),
      ],
    ])
    win.transform = transform
    win.expectsMediaDataInRealTime = false
    writer.add(win)

    reader.startReading()
    writer.startWriting()
    writer.startSession(atSourceTime: .zero)
    let q = DispatchQueue(label: "w")
    await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
      win.requestMediaDataWhenReady(on: q) {
        while win.isReadyForMoreMediaData {
          if let sb = rout.copyNextSampleBuffer() { win.append(sb) }
          else { win.markAsFinished(); c.resume(); return }
        }
      }
    }
    await writer.finishWriting()
    if writer.status != .completed { throw writer.error ?? NSError(domain: "write failed", code: 3) }
  } catch { print("error:", error); code = 1 }
  sem.signal()
}
sem.wait()
exit(code)
