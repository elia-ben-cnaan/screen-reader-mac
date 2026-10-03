// ScreenReader — passive screen text reader (macOS 14+). Single file, no deps.
// Capture (ScreenCaptureKit, in memory) -> cheap frame fingerprint -> Apple Vision OCR only on change -> panel.
import Cocoa
import Vision
import ScreenCaptureKit

let interval: TimeInterval = 1.5          // seconds between capture checks
let changeThreshold: Double = 0.004       // mean pixel diff (0..1) that counts as "changed"

// MARK: OCR (shared by app + --selftest)
let tesseractPath = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"].first { FileManager.default.isExecutableFile(atPath: $0) }

// Apple Vision has no Hebrew, so use Tesseract (heb+eng) when installed. PNG goes through a pipe, never to disk.
func ocr(_ image: CGImage) throws -> String {
    if let t = tesseractPath { return try tesseract(t, image) }
    return try visionOCR(image)
}

func tesseract(_ path: String, _ image: CGImage) throws -> String {
    let data = NSMutableData()
    let dest = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, image, nil); CGImageDestinationFinalize(dest)
    let p = Process(); p.executableURL = URL(fileURLWithPath: path)
    p.arguments = ["stdin", "stdout", "-l", "heb+eng", "--psm", "3"]
    let inp = Pipe(), out = Pipe(); p.standardInput = inp; p.standardOutput = out; p.standardError = FileHandle.nullDevice
    try p.run()
    DispatchQueue.global().async { inp.fileHandleForWriting.write(data as Data); try? inp.fileHandleForWriting.close() }
    let result = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
    return String(decoding: result, as: UTF8.self)
}

func visionOCR(_ image: CGImage) throws -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    let supported = (try? req.supportedRecognitionLanguages()) ?? []
    let wanted = ["he-IL", "en-US"].filter { supported.contains($0) }
    if !wanted.isEmpty { req.recognitionLanguages = wanted }
    try VNImageRequestHandler(cgImage: image).perform([req])
    let obs = (req.results ?? []).sorted {           // reading order: top->bottom, then by x
        abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.01
            ? $0.boundingBox.midY > $1.boundingBox.midY
            : $0.boundingBox.minX < $1.boundingBox.minX
    }
    return obs.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func normalize(_ s: String) -> String {
    s.split(separator: "\n").map { $0.split(whereSeparator: \.isWhitespace).joined(separator: " ") }
        .filter { !$0.isEmpty }.joined(separator: "\n")
}

// 64x36 grayscale thumbnail used to skip OCR when the screen didn't change.
func fingerprint(_ image: CGImage) -> [UInt8] {
    let w = 64, h = 36
    var px = [UInt8](repeating: 0, count: w * h)
    px.withUnsafeMutableBytes { buf in
        let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        ctx.interpolationQuality = .low
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    }
    return px
}
func diff(_ a: [UInt8], _ b: [UInt8]) -> Double {
    guard a.count == b.count, !a.isEmpty else { return 1 }
    var t = 0; for i in 0..<a.count { t += abs(Int(a[i]) - Int(b[i])) }
    return Double(t) / Double(a.count * 255)
}

// MARK: Practice — explain the practice question currently on screen (on demand, never clicks/types)
// Server proxy (server/proxy.py) holds the model key; app only knows URL + token.
// Defaults are baked at build time (Config.swift); ~/.config/screenreader/server ("URL\nTOKEN") overrides.
let serverFile = NSString(string: "~/.config/screenreader/server").expandingTildeInPath
func serverConfig() -> (url: String, token: String) {
    let l = ((try? String(contentsOfFile: serverFile, encoding: .utf8)) ?? "").split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }
    return l.count >= 2 ? (l[0], l[1]) : (defaultServer, defaultToken)
}

// MARK: Layout — is there non-text graphics on screen, and where is the question?
// Text glyphs are small connected blobs of similar height; shapes, grids and figures are much taller blobs.
let edgeIgnore = (top: 0.04, bottom: 0.0)   // menu bar strip; raise bottom if the Dock is always visible
let graphicHeight = 2.5                     // blob taller than this x median glyph height = graphics

struct Layout { var visual: Bool; var crop: CGRect; var graphics: Int }

// ponytail: crop = graphics + ink rows near them, not true question segmentation; fine for one question per screen.
func layout(_ image: CGImage) -> Layout {
    let W = min(1200, image.width), H = max(1, image.height * W / image.width)
    var px = [UInt8](repeating: 0, count: W * H)
    px.withUnsafeMutableBytes { buf in
        let ctx = CGContext(data: buf.baseAddress, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W,
                            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: W, height: H))
    }
    var hist = [Int](repeating: 0, count: 256); for v in px { hist[Int(v)] += 1 }
    let bg = hist.indices.max { hist[$0] < hist[$1] }!
    let y0 = Int(Double(H) * edgeIgnore.top), y1 = H - Int(Double(H) * edgeIgnore.bottom)
    var ink = [Bool](repeating: false, count: W * H)
    for y in y0..<y1 { for x in 0..<W where abs(Int(px[y * W + x]) - bg) > 40 { ink[y * W + x] = true } }
    // Connected components (8-neighbour flood fill) -> bounding boxes.
    var seen = [Bool](repeating: false, count: W * H), blobs: [CGRect] = [], stack: [Int] = []
    for start in 0..<(W * H) where ink[start] && !seen[start] {
        var x0 = W, x1 = 0, yA = H, yB = 0, pixels: [Int] = []
        seen[start] = true; stack.append(start)
        while let i = stack.popLast() {
            let x = i % W, y = i / W
            pixels.append(i)
            x0 = min(x0, x); x1 = max(x1, x); yA = min(yA, y); yB = max(yB, y)
            for dy in -1...1 { for dx in -1...1 {
                let nx = x + dx, ny = y + dy
                guard nx >= 0, nx < W, ny >= 0, ny < H else { continue }
                let j = ny * W + nx
                if ink[j] && !seen[j] { seen[j] = true; stack.append(j) }
            } }
        }
        // Plain rectangular frames (cards, section borders, input boxes) are page chrome, not figures.
        let inner = pixels.filter { let x = $0 % W, y = $0 / W; return x > x0 + 3 && x < x1 - 3 && y > yA + 3 && y < yB - 3 }.count
        if yB - yA > 20 && inner * 20 < pixels.count { continue }
        // Solid wide bars (buttons, header/progress bars) are UI chrome too.
        let bw = x1 - x0 + 1, bh = yB - yA + 1
        if bw > 2 * bh && pixels.count * 100 > bw * bh * 85 { continue }
        blobs.append(CGRect(x: x0, y: yA, width: x1 - x0 + 1, height: yB - yA + 1))
    }
    let hs = blobs.map(\.height).filter { $0 >= 3 }.sorted()
    let glyph = hs.isEmpty ? 10 : hs[hs.count / 2]
    let graphics = blobs.filter { $0.height > glyph * graphicHeight }
    guard var crop = graphics.first else { return Layout(visual: false, crop: .zero, graphics: 0) }
    for g in graphics { crop = crop.union(g) }
    let reach = Double(H) * 0.25                                  // question text above, options below
    for b in blobs where b.maxY > crop.minY - reach && b.minY < crop.maxY + reach { crop = crop.union(b) }
    crop = crop.insetBy(dx: -24, dy: -8).intersection(CGRect(x: 0, y: 0, width: W, height: H))
    let k = Double(image.width) / Double(W)                      // back to full-resolution pixels
    return Layout(visual: true, crop: CGRect(x: crop.minX * k, y: crop.minY * k, width: crop.width * k, height: crop.height * k), graphics: graphics.count)
}

// Cropped PNG, downscaled to <=1568px long side. In memory only.
func croppedPNG(_ image: CGImage, _ rect: CGRect) -> Data? {
    guard let c = image.cropping(to: rect.integral) else { return nil }
    let s = min(1, 1568 / Double(max(c.width, c.height)))
    let w = Int(Double(c.width) * s), h = Int(Double(c.height) * s)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.interpolationQuality = .high
    ctx.draw(c, in: CGRect(x: 0, y: 0, width: w, height: h))
    guard let out = ctx.makeImage() else { return nil }
    let data = NSMutableData()
    let dest = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, out, nil); CGImageDestinationFinalize(dest)
    return data as Data
}

// Same question -> same key. Clock-like "12:34" (simulator timers) is ignored; visual questions also key on the crop.
func questionKey(_ text: String, _ image: CGImage, _ l: Layout) -> String {
    let t = text.replacingOccurrences(of: #"\b\d{1,2}:\d{2}(:\d{2})?\b"#, with: "", options: .regularExpression)
    guard l.visual, let c = image.cropping(to: l.crop.integral) else { return t }
    return t + "|" + fingerprint(c).map { String($0 >> 5) }.joined()
}
nonisolated(unsafe) var answerCache: [String: (mode: String, answer: String)] = [:]

// TEXT -> text only; VISUAL/MIXED -> cropped screenshot + text. Repeated question -> cached, no request.
func explain(_ image: CGImage, _ screenText: String, _ onPartial: @escaping @Sendable (String) -> Void = { _ in }) async throws -> (mode: String, answer: String, cached: Bool) {
    let l = layout(image)
    let key = questionKey(screenText, image, l)
    if let c = answerCache[key] { return (c.mode, c.answer, true) }
    let png = l.visual ? croppedPNG(image, l.crop) : nil
    let mode = png == nil ? "TEXT" : "VISUAL"
    let answer = try await ask(screenText, png, onPartial)
    answerCache[key] = (mode, answer)
    return (mode, answer, false)
}

// Streams the answer from the server; onPartial gets the text so far.
func ask(_ text: String, _ png: Data?, _ onPartial: @escaping @Sendable (String) -> Void) async throws -> String {
    let c = serverConfig()
    guard let url = URL(string: c.url + "/ask"), !c.token.isEmpty else { return "No server configured (\(serverFile))." }
    var r = URLRequest(url: url)
    r.httpMethod = "POST"; r.timeoutInterval = 60
    r.setValue("application/json", forHTTPHeaderField: "content-type")
    r.setValue(c.token, forHTTPHeaderField: "X-Token")
    r.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "image": png?.base64EncodedString() as Any])
    let (bytes, resp) = try await URLSession.shared.bytes(for: r)
    var acc = ""
    for try await line in bytes.lines { acc += (acc.isEmpty ? "" : "\n") + line; onPartial(acc) }
    if let h = resp as? HTTPURLResponse, h.statusCode != 200 { return "Server error \(h.statusCode): \(acc)" }
    return acc.isEmpty ? "No answer" : acc
}

// Main display, excluding this app's own window. Image lives in memory only — never written to disk.
func captureScreen() async throws -> CGImage {
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    let screenID = NSScreen.main?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
    guard let display = content.displays.first(where: { $0.displayID == screenID }) ?? content.displays.first
    else { throw NSError(domain: "ScreenReader", code: 1, userInfo: [NSLocalizedDescriptionKey: "No display"]) }
    let me = content.applications.filter { $0.processID == ProcessInfo.processInfo.processIdentifier }
    let filter = SCContentFilter(display: display, excludingApplications: me, exceptingWindows: [])
    let cfg = SCStreamConfiguration()
    let scale = Int(NSScreen.main?.backingScaleFactor ?? 2)
    cfg.width = display.width * scale
    cfg.height = display.height * scale
    cfg.showsCursor = false
    return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
}

// MARK: App — small native window: what's on screen, the answer, nothing else.
// Server reply lines: "ANSWER: ג" / "Q: <question>" / "A: <answer>". Parsed as they stream in.
func parseReply(_ s: String) -> (label: String?, q: String?, a: String?) {
    var label: String?, q: String?, a: String?
    for line in s.split(whereSeparator: \.isNewline) {
        let l = line.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "**", with: "")
        if l.hasPrefix("ANSWER:") { let v = l.dropFirst(7).trimmingCharacters(in: .whitespaces); label = v == "-" || v.isEmpty ? nil : v }
        else if l.hasPrefix("Q:") { q = l.dropFirst(2).trimmingCharacters(in: .whitespaces) }
        else if l.hasPrefix("A:") { a = l.dropFirst(2).trimmingCharacters(in: .whitespaces) }
    }
    return (label, q, a)
}

@MainActor final class App: NSObject, NSApplicationDelegate {
    enum State { case idle, reading, paused, error }
    var panel: NSPanel!
    let dot = NSTextField(labelWithString: "●")
    let status = NSTextField(labelWithString: "")
    let onScreen = NSTextField(labelWithString: "על המסך")
    let question = NSTextField(wrappingLabelWithString: "")
    let answer = NSTextField(labelWithString: "")
    let label = NSTextField(labelWithString: "")
    var timer: Timer?
    var busy = false
    var lastPrint: [UInt8] = []
    var lastText = ""
    var lastImage: CGImage?          // latest frame, memory only; replaced every capture
    var askTask: Task<Void, Never>?
    var state: State = .idle { didSet { render() } }

    func applicationDidFinishLaunching(_ n: Notification) {
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 260),
                        styleMask: [.titled, .closable, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        panel.title = "קורא מסך"
        panel.level = .floating
        panel.isFloatingPanel = true
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.setFrameTopLeftPoint(NSPoint(x: (NSScreen.main?.visibleFrame.maxX ?? 800) - 380,
                                           y: (NSScreen.main?.visibleFrame.maxY ?? 800) - 20))
        dot.font = .systemFont(ofSize: 10)
        status.font = .systemFont(ofSize: 12); status.textColor = .secondaryLabelColor
        onScreen.font = .systemFont(ofSize: 12, weight: .medium); onScreen.textColor = .secondaryLabelColor
        question.font = .systemFont(ofSize: 15); question.maximumNumberOfLines = 3
        question.lineBreakMode = .byTruncatingTail; question.preferredMaxLayoutWidth = 312
        answer.font = .systemFont(ofSize: 34, weight: .bold)
        answer.lineBreakMode = .byTruncatingTail; answer.minimumScaleFactor = 0.5; answer.allowsDefaultTighteningForTruncation = true
        label.font = .systemFont(ofSize: 14, weight: .semibold); label.textColor = .systemBlue
        for f in [status, onScreen, question, answer, label] { f.alignment = .right; f.baseWritingDirection = .rightToLeft }

        let statusRow = NSStackView(views: [dot, status])
        statusRow.spacing = 6; statusRow.userInterfaceLayoutDirection = .rightToLeft
        let click = NSClickGestureRecognizer(target: self, action: #selector(toggleRun))
        statusRow.addGestureRecognizer(click)                  // click the status line = start / pause
        statusRow.toolTip = "לחיצה: הפעלה / השהיה"

        let stack = NSStackView(views: [statusRow, onScreen, question, answer, label])
        stack.orientation = .vertical; stack.alignment = .centerX; stack.spacing = 8
        stack.setCustomSpacing(18, after: statusRow); stack.setCustomSpacing(18, after: question)
        stack.setCustomSpacing(2, after: answer)
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 24, bottom: 20, right: 24)
        for v in [statusRow, onScreen, question, answer, label] as [NSView] {   // full width minus margins; text right-aligned
            v.translatesAutoresizingMaskIntoConstraints = false
            v.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48).isActive = true
        }
        let bg = NSVisualEffectView(); bg.material = .popover; bg.blendingMode = .behindWindow; bg.state = .active
        bg.addSubview(stack); stack.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: bg.topAnchor), stack.bottomAnchor.constraint(lessThanOrEqualTo: bg.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: bg.leadingAnchor), stack.trailingAnchor.constraint(equalTo: bg.trailingAnchor),
            stack.widthAnchor.constraint(equalToConstant: 360),
        ])
        panel.contentView = bg
        panel.orderFrontRegardless()
        render()
        start()                                                 // automatic from launch
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }

    func render() {
        let (text, color): (String, NSColor) = switch state {
            case .idle: ("מוכן", .secondaryLabelColor)
            case .reading: ("מקליט · אוטומטי", .systemRed)
            case .paused: ("מושהה · לחץ להמשך", .systemOrange)
            case .error: ("שגיאה", .systemRed)
        }
        status.stringValue = text; dot.textColor = color
    }

    func showAnswer(_ q: String, _ a: String, _ l: String) {
        question.stringValue = q; answer.stringValue = a; label.stringValue = l
        answer.textColor = .labelColor
    }
    func showThinking(_ q: String) { showAnswer(q, "• • •", ""); answer.textColor = .tertiaryLabelColor }

    @objc func toggleRun() { state == .reading ? pause() : start() }

    // New question on screen -> cancel the old request, ask about the new one.
    func askAuto(_ img: CGImage, _ text: String) {
        askTask?.cancel()
        let preview = text.split(whereSeparator: \.isNewline).prefix(3).joined(separator: " ")
        showThinking(preview)
        askTask = Task {
            let r = try? await Task.detached {
                try await explain(img, text) { p in
                    Task { @MainActor in
                        let x = parseReply(p)
                        if let q = x.q { self.question.stringValue = q }
                        if let a = x.a, !a.isEmpty { self.answer.stringValue = a; self.answer.textColor = .labelColor }
                    }
                }
            }.value
            guard !Task.isCancelled else { return }
            guard let r else { showAnswer(preview, "אין חיבור", "השרת לא ענה"); return }
            let x = parseReply(r.answer)
            if x.a == nil { showAnswer(preview, "—", String(r.answer.prefix(80))); return }   // server message / error
            showAnswer(x.q ?? preview, x.a!, x.label.map { "תשובה \($0)" } ?? "")
        }
    }

    func start() {
        if !CGPreflightScreenCaptureAccess() {
            CGRequestScreenCaptureAccess()
            state = .error
            showAnswer("System Settings ← Privacy & Security ← Screen & System Audio Recording ← הפעל את ScreenReader, ואז סגור ופתח מחדש.",
                       "צריך הרשאה", "הקלטת מסך")
            return
        }
        state = .reading
        lastPrint = []   // force fresh OCR on resume
        tick()
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { _ in
            Task { @MainActor in self.tick() }
        }
        timer?.tolerance = 0.3
    }
    func pause() { timer?.invalidate(); timer = nil; askTask?.cancel(); state = .paused }

    func tick() {
        guard state == .reading, !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                let img = try await capture()
                let fp = fingerprint(img)
                if diff(fp, lastPrint) < changeThreshold { return }
                lastPrint = fp
                lastImage = img
                let text = try await Task.detached(priority: .utility) { normalize(try ocr(img)) }.value
                let stable = text.replacingOccurrences(of: #"\b\d{1,2}:\d{2}(:\d{2})?\b"#, with: "", options: .regularExpression)
                if stable != lastText, !text.isEmpty { lastText = stable; askAuto(img, text) }   // clock ticking != new question
            } catch {
                state = .error; timer?.invalidate(); timer = nil
                showAnswer(error.localizedDescription, "שגיאה", "")
            }
        }
    }

    func capture() async throws -> CGImage { try await captureScreen() }
}

// MARK: entry
let args = CommandLine.arguments
func loadImage(_ path: String) -> CGImage {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { print("CANNOT READ \(path)"); exit(2) }
    return img
}
if args.count >= 3, args[1] == "--layout" {    // print TEXT/VISUAL + crop per image (used by tests, no network)
    for path in args[2...] {
        let img = loadImage(path), l = layout(img)
        if let dir = ProcessInfo.processInfo.environment["SR_CROP_DIR"], l.visual, let png = croppedPNG(img, l.crop) {   // debug: inspect crops
            try? png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("crop-" + (path as NSString).lastPathComponent))
        }
        print("\((path as NSString).lastPathComponent) \(l.visual ? "VISUAL" : "TEXT") graphics=\(l.graphics) crop=\(l.crop.integral)")
    }
    exit(0)
}
if args.count >= 4, args[1] == "--e2e" {
    // Test driver mode: for each "go <tag>" line read from <cmd fifo>, run the real pipeline
    // (ScreenCaptureKit capture -> OCR -> layout -> Practice) and append one JSON line to <out>.
    let cmds = FileHandle(forReadingAtPath: args[2])!, outURL = URL(fileURLWithPath: args[3])
    FileManager.default.createFile(atPath: outURL.path, contents: nil)
    let out = try! FileHandle(forWritingTo: outURL)
    Task.detached {
        var buf = Data()
        while true {
            let chunk = cmds.availableData
            if chunk.isEmpty { exit(0) }                      // driver closed the fifo
            buf += chunk
            while let nl = buf.firstIndex(of: 10) {
                let line = String(decoding: buf[..<nl], as: UTF8.self); buf = Data(buf[(nl + 1)...])
                guard line.hasPrefix("go ") else { if line == "quit" { exit(0) }; continue }
                var row: [String: Any] = ["tag": String(line.dropFirst(3))]
                let t0 = Date()
                do {
                    let img = try await captureScreen()
                    let tCap = Date()
                    let text = normalize(try ocr(img))
                    let r = try await explain(img, text)
                    row.merge(["mode": r.mode, "answer": r.answer, "cached": r.cached, "ocr": text,
                               "ms_capture": Int(tCap.timeIntervalSince(t0) * 1000), "ms_total": Int(Date().timeIntervalSince(t0) * 1000)]) { $1 }
                } catch { row["error"] = "\(error)" }
                out.write(try! JSONSerialization.data(withJSONObject: row) + Data("\n".utf8))
            }
        }
    }
    NSApplication.shared.setActivationPolicy(.prohibited)
    NSApplication.shared.run()
}
if args.count >= 3, args[1] == "--explain" {   // full Practice pipeline on an image file (uses the server proxy)
    let img = loadImage(args[2])
    let text = normalize((try? ocr(img)) ?? "")
    let sem = DispatchSemaphore(value: 0)
    Task { let r = try? await explain(img, text); print("[\(r?.mode ?? "?")\(r?.cached == true ? " cached" : "")]\n\(r?.answer ?? "failed")"); sem.signal() }
    sem.wait(); exit(0)
}
if args.count >= 3, args[1] == "--selftest" {
    // OCR an image file and print the text (used by test/run-tests.sh). No permissions needed.
    for path in args[2...] {
        guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { print("CANNOT READ \(path)"); exit(2) }
        let t0 = Date()
        let text = normalize((try? ocr(img)) ?? "")
        print("=== \(path) (\(Int(Date().timeIntervalSince(t0) * 1000)) ms)\n\(text)")
        let a = fingerprint(img)
        print("fingerprint self-diff: \(diff(a, fingerprint(img)))")
    }
    exit(0)
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = MainActor.assumeIsolated { App() }
app.delegate = delegate
app.run()
