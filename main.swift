// ScreenReader — passive screen text reader (macOS 14+). Single file, no deps.
// Capture (ScreenCaptureKit, in memory) -> cheap frame fingerprint -> Apple Vision OCR only on change -> panel.
import Cocoa
import SwiftUI
import Carbon.HIToolbox
import Vision
import ScreenCaptureKit

let interval: TimeInterval = 1.5          // seconds between capture checks
let changeThreshold: Double = 0.0015      // share of fingerprint cells that changed visibly = "new screen"
let forceEvery = 4                         // re-OCR every Nth tick anyway (safety net, OCR is local)

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
// 192x108 is fine enough that swapping one line of question text changes many cells.
func fingerprint(_ image: CGImage, w: Int = 192, h: Int = 108) -> [UInt8] {
    var px = [UInt8](repeating: 0, count: w * h)
    px.withUnsafeMutableBytes { buf in
        let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        ctx.interpolationQuality = .low
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    }
    return px
}
// Word-set overlap (Jaccard): re-reading the same screen gives ~1.0 even when OCR differs by a character or two.
func similarity(_ a: String, _ b: String) -> Double {
    let x = Set(a.split(whereSeparator: { $0.isWhitespace })), y = Set(b.split(whereSeparator: { $0.isWhitespace }))
    if x.isEmpty && y.isEmpty { return 1 }
    return Double(x.intersection(y).count) / Double(x.union(y).count)
}
func diff(_ a: [UInt8], _ b: [UInt8]) -> Double {
    guard a.count == b.count, !a.isEmpty else { return 1 }
    var n = 0; for i in 0..<a.count where abs(Int(a[i]) - Int(b[i])) > 12 { n += 1 }
    return Double(n) / Double(a.count)
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
    return t + "|" + fingerprint(c, w: 64, h: 36).map { String($0 >> 5) }.joined()
}
nonisolated(unsafe) var answerCache: [String: (mode: String, answer: String)] = [:]

// TEXT -> text only; VISUAL/MIXED -> cropped screenshot + text. Repeated question -> cached, no request.
// context = current unit instructions (+ reading passage); visualUnit = always send the image.
func explain(_ image: CGImage, _ screenText: String, context: String = "", visualUnit: Bool = false,
             _ onPartial: @escaping @Sendable (String) -> Void = { _ in }) async throws -> (mode: String, answer: String, cached: Bool) {
    let l = layout(image)
    let key = questionKey(screenText, image, l) + "|" + String(context.hashValue)
    if let c = answerCache[key] { return (c.mode, c.answer, true) }
    let png = l.visual ? croppedPNG(image, l.crop) : visualUnit ? croppedPNG(image, CGRect(x: 0, y: 0, width: image.width, height: image.height)) : nil
    let mode = png == nil ? "TEXT" : "VISUAL"
    let answer = try await ask(screenText, png, context, onPartial)
    answerCache[key] = (mode, answer)
    return (mode, answer, false)
}

// Streams the answer from the server; onPartial gets the text so far.
func ask(_ text: String, _ png: Data?, _ context: String, _ onPartial: @escaping @Sendable (String) -> Void) async throws -> String {
    let c = serverConfig()
    guard let url = URL(string: c.url + "/ask"), !c.token.isEmpty else { return "No server configured (\(serverFile))." }
    var r = URLRequest(url: url)
    r.httpMethod = "POST"; r.timeoutInterval = 60
    r.setValue("application/json", forHTTPHeaderField: "content-type")
    r.setValue(c.token, forHTTPHeaderField: "X-Token")
    r.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "image": png?.base64EncodedString() as Any, "context": context])
    let (bytes, resp) = try await URLSession.shared.bytes(for: r)
    var acc = ""
    for try await line in bytes.lines { acc += (acc.isEmpty ? "" : "\n") + line; onPartial(acc) }
    if let h = resp as? HTTPURLResponse, h.statusCode != 200 { return "Server error \(h.statusCode): \(acc)" }
    return acc.isEmpty ? "No answer" : acc
}

// What to read: whole main display, one app's window, or a dragged region. Saved in UserDefaults.
enum Source: Equatable {
    case screen
    case window(bundleID: String, windowID: CGWindowID, name: String)
    case region(CGRect)   // main display points, top-left origin

    var label: String {
        switch self {
        case .screen: "כל המסך"
        case .window(_, _, let n): n
        case .region: "אזור נבחר"
        }
    }
    static func load() -> Source {
        let d = UserDefaults.standard
        switch d.string(forKey: "source") {
        case "window": return .window(bundleID: d.string(forKey: "srcBundle") ?? "", windowID: CGWindowID(d.integer(forKey: "srcWindow")), name: d.string(forKey: "srcName") ?? "")
        case "region": if let s = d.string(forKey: "srcRect") { return .region(NSRectFromString(s)) }
        default: break
        }
        return .screen
    }
    func save() {
        let d = UserDefaults.standard
        switch self {
        case .screen: d.set("screen", forKey: "source")
        case .window(let b, let w, let n): d.set("window", forKey: "source"); d.set(b, forKey: "srcBundle"); d.set(Int(w), forKey: "srcWindow"); d.set(n, forKey: "srcName")
        case .region(let r): d.set("region", forKey: "source"); d.set(NSStringFromRect(r), forKey: "srcRect")
        }
    }
}
nonisolated(unsafe) var source = Source.load()
nonisolated(unsafe) var visibleWindows: [(bundleID: String, windowID: CGWindowID, name: String)] = []   // refreshed every capture, for the menu

// Image lives in memory only — never written to disk.
func captureScreen() async throws -> CGImage {
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    let me = ProcessInfo.processInfo.processIdentifier
    let wins = content.windows.filter { w in
        guard let app = w.owningApplication, app.processID != me, w.windowLayer == 0, w.frame.width > 200, w.frame.height > 150 else { return false }
        return true
    }
    visibleWindows = wins.map { w in
        let app = w.owningApplication!.applicationName, t = w.title ?? ""
        return (w.owningApplication!.bundleIdentifier, w.windowID, t.isEmpty ? app : "\(app) — \(t.prefix(40))")
    }
    let scale = Int(NSScreen.main?.backingScaleFactor ?? 2)
    let cfg = SCStreamConfiguration(); cfg.showsCursor = false
    if case .window(let bundle, let id, _) = source {
        // same window if still open, else the app's largest window (browser tab titles change)
        if let w = wins.first(where: { $0.windowID == id })
            ?? wins.filter({ $0.owningApplication?.bundleIdentifier == bundle }).max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) {
            cfg.width = Int(w.frame.width) * scale; cfg.height = Int(w.frame.height) * scale
            return try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: w), configuration: cfg)
        }
        throw NSError(domain: "ScreenReader", code: 2, userInfo: [NSLocalizedDescriptionKey: "החלון שנבחר סגור — בחר מקור אחר מהתפריט"])
    }
    let screenID = NSScreen.main?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
    guard let display = content.displays.first(where: { $0.displayID == screenID }) ?? content.displays.first
    else { throw NSError(domain: "ScreenReader", code: 1, userInfo: [NSLocalizedDescriptionKey: "No display"]) }
    let filter = SCContentFilter(display: display, excludingApplications: content.applications.filter { $0.processID == me }, exceptingWindows: [])
    if case .region(let r) = source {
        cfg.sourceRect = r
        cfg.width = Int(r.width) * scale; cfg.height = Int(r.height) * scale
    } else {
        cfg.width = display.width * scale; cfg.height = display.height * scale
    }
    return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
}

// Full-screen dim overlay: drag a rectangle, Esc cancels. Returns the rect in display points, top-left origin.
@MainActor final class RegionPicker: NSWindow {
    var start: NSPoint?, box = NSView(), done: ((CGRect?) -> Void)?
    init(_ done: @escaping (CGRect?) -> Void) {
        let f = NSScreen.main!.frame
        super.init(contentRect: f, styleMask: .borderless, backing: .buffered, defer: false)
        self.done = done
        level = .screenSaver; isOpaque = false; backgroundColor = NSColor.black.withAlphaComponent(0.25); ignoresMouseEvents = false
        box.wantsLayer = true; box.layer?.borderColor = NSColor.systemBlue.cgColor; box.layer?.borderWidth = 2
        box.layer?.backgroundColor = NSColor.systemBlue.withAlphaComponent(0.12).cgColor
        contentView = NSView(); contentView!.addSubview(box)
        let hint = NSTextField(labelWithString: "גרור מסביב לאזור של השאלות · Esc לביטול")
        hint.font = .systemFont(ofSize: 20, weight: .semibold); hint.textColor = .white; hint.sizeToFit()
        hint.setFrameOrigin(NSPoint(x: (f.width - hint.frame.width) / 2, y: f.height * 0.8)); contentView!.addSubview(hint)
    }
    override var canBecomeKey: Bool { true }
    override func mouseDown(with e: NSEvent) { start = e.locationInWindow; box.frame = .zero }
    override func mouseDragged(with e: NSEvent) {
        guard let s = start else { return }
        let p = e.locationInWindow
        box.frame = NSRect(x: min(s.x, p.x), y: min(s.y, p.y), width: abs(p.x - s.x), height: abs(p.y - s.y))
    }
    override func mouseUp(with e: NSEvent) {
        let r = box.frame, h = frame.height
        finish(r.width > 40 && r.height > 30 ? CGRect(x: r.minX, y: h - r.maxY, width: r.width, height: r.height) : nil)
    }
    override func keyDown(with e: NSEvent) { if e.keyCode == 53 { finish(nil) } }
    func finish(_ r: CGRect?) { orderOut(nil); done?(r); done = nil }
}

// MARK: Session model — units (from instruction screens) holding answered questions. Saved as JSON while running.
struct Item: Codable, Identifiable { var id = UUID(); var num: String; var question: String; var answer: String; var label: String; var why: String; var low: Bool; var ms: Int; var trap: String? }
struct Unit: Codable, Identifiable { var id = UUID(); var title: String; var num: String; var summary: String; var visual: Bool; var passage = ""; var items: [Item] = [] }
struct Session: Codable { var start = Date(); var end: Date?; var units: [Unit] = [] }
let sessionURL: URL = {
    let d = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("ScreenReader")
    try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
    return d.appendingPathComponent("session.json")
}()
// Every finished session is kept as sessions/YYYY-MM-DD HH.mm.json
let sessionsDir: URL = {
    let d = sessionURL.deletingLastPathComponent().appendingPathComponent("sessions")
    try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
    return d
}()

// Server reply: "KEY: value" lines (format in server/proxy.py).
struct Reply {
    var f: [String: String] = [:]
    var checking = false
    init(_ s: String) {
        for line in s.split(whereSeparator: \.isNewline) {
            let l = line.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "**", with: "")
            if l == "CHECKING" { checking = true; continue }
            if let i = l.firstIndex(of: ":") { f[String(l[..<i]).uppercased()] = l[l.index(after: i)...].trimmingCharacters(in: .whitespaces) }
        }
    }
    subscript(_ k: String) -> String { let v = f[k] ?? ""; return v == "-" ? "" : v }
    var kind: String { self["KIND"].lowercased() }
}

func refreshWindowList() async {
    guard let content = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true) else { return }
    let me = ProcessInfo.processInfo.processIdentifier
    visibleWindows = content.windows.filter { w in
        guard let app = w.owningApplication, app.processID != me, w.windowLayer == 0, w.frame.width > 200, w.frame.height > 150 else { return false }
        return true
    }.map { w in
        let app = w.owningApplication!.applicationName, t = w.title ?? ""
        return (w.owningApplication!.bundleIdentifier, w.windowID, t.isEmpty ? app : "\(app) — \(t.prefix(40))")
    }
}

// MARK: Model
@MainActor final class Model: ObservableObject {
    enum Phase { case idle, running, paused }
    @Published var phase = Phase.idle
    @Published var session: Session?
    @Published var current: Item?
    @Published var instructions: Unit?          // last screen was a unit intro
    @Published var status = ""                  // waiting / thinking / errors
    @Published var thinking = false
    @Published var pending = ""                 // question text while thinking
    @Published var sourceLabel = source.label
    @Published var windows: [(bundleID: String, windowID: CGWindowID, name: String)] = []
    @Published var showSummary = false
    @Published var needsPermission = false
    @Published var showList = UserDefaults.standard.bool(forKey: "showList") { didSet { UserDefaults.standard.set(showList, forKey: "showList") } }
    var hasChosenSource: Bool { UserDefaults.standard.string(forKey: "source") != nil }
    var onFloat: (() -> Void)?
    var picker: RegionPicker?
    private var timer: Timer?, busy = false, ticks = 0, lastPrint: [UInt8] = [], lastText = "", lastImage: CGImage?

    init() {
        if let d = try? Data(contentsOf: sessionURL), let s = try? JSONDecoder().decode(Session.self, from: d), s.end == nil, !s.units.isEmpty {
            session = s; phase = .paused; status = "סשן קודם נשמר · ⌥⌘P להמשך"   // app closed mid-session: nothing lost
            current = s.units.last?.items.last
        }
    }

    var unit: Unit? { session?.units.last }
    func archive() {
        guard let s = session, !s.units.isEmpty, let d = try? JSONEncoder().encode(s) else { return }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH.mm"
        try? d.write(to: sessionsDir.appendingPathComponent(f.string(from: s.start) + ".json"))
        try? summaryText().write(to: sessionsDir.appendingPathComponent(f.string(from: s.start) + ".txt"), atomically: true, encoding: .utf8)
    }
    // Reset: archive whatever exists, clear the screen, ready for a new session.
    func newSession() {
        timer?.invalidate(); timer = nil; thinking = false
        if session?.end == nil { session?.end = Date() }
        archive(); session = nil; current = nil; instructions = nil; status = ""; phase = .idle
        try? FileManager.default.removeItem(at: sessionURL); answerCache.removeAll(); lastPrint = []; lastText = ""
    }
    func save() { if let s = session, let d = try? JSONEncoder().encode(s) { try? d.write(to: sessionURL) } }

    func loadWindows() { Task { await refreshWindowList(); windows = visibleWindows } }
    func setSource(_ s: Source) { source = s; s.save(); sourceLabel = s.label; lastPrint = []; lastText = "" }
    func pickRegion() {
        picker = RegionPicker { [weak self] r in if let r { self?.setSource(.region(r)) }; self?.picker = nil }
        picker?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }

    // ⌥⌘S
    func startStop() {
        if phase == .idle { start() } else { finish() }
    }
    func start() {
        guard CGPreflightScreenCaptureAccess() else { CGRequestScreenCaptureAccess(); needsPermission = true; return }
        needsPermission = false
        if session == nil || session?.end != nil { session = Session(); current = nil; instructions = nil }
        phase = .running; status = "ממתין לשאלה"; lastPrint = []; lastText = ""
        tick()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { _ in Task { @MainActor in self.tick() } }
        timer?.tolerance = 0.3
    }
    func finish() {
        timer?.invalidate(); timer = nil; thinking = false
        session?.end = Date(); save(); archive(); phase = .idle; status = ""
        if session?.units.isEmpty == false { showSummary = true }
    }
    // ⌥⌘P
    func pauseResume() {
        switch phase {
        case .running: timer?.invalidate(); timer = nil; thinking = false; phase = .paused; status = "מושהה"
        case .paused: start()
        case .idle: start()
        }
    }
    // ⌥⌘R: ask again about what's on screen now, bypassing the cache
    func askAgain() {
        guard let img = lastImage, !lastText.isEmpty else { return }
        answerCache.removeAll(); handle(img, lastText, replace: true)
    }

    func tick() {
        guard phase == .running, !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                let img = try await captureScreen()
                windows = visibleWindows
                let fp = fingerprint(img)
                ticks += 1
                if diff(fp, lastPrint) < changeThreshold && ticks % forceEvery != 0 { return }
                lastPrint = fp; lastImage = img
                let text = try await Task.detached(priority: .utility) { normalize(try ocr(img)) }.value
                let stable = text.replacingOccurrences(of: #"\b\d{1,2}:\d{2}(:\d{2})?\b"#, with: "", options: .regularExpression)
                // clock ticking or OCR noise on the same screen != new screen
                if !text.isEmpty, similarity(stable, lastText) < 0.9 { lastText = stable; handle(img, text) }
            } catch {
                status = error.localizedDescription      // e.g. chosen window closed; keep trying
            }
        }
    }

    func context() -> String {
        guard let u = unit else { return "" }
        return "Unit \(u.num) \(u.title): \(u.summary)" + (u.passage.isEmpty ? "" : "\nREADING PASSAGE:\n\(u.passage)")
    }

    // Every screen gets its answer, even if you already moved on: requests run in parallel and are
    // filed strictly in screen order, so a late answer lands in its own unit/question.
    private var seq = 0, nextApply = 1, done: [Int: (Reply, String, Int, String)?] = [:]
    @Published var inflight = 0
    func handle(_ img: CGImage, _ text: String, replace: Bool = false) {
        seq += 1; let my = seq
        let ctx = context()
        let t0 = Date()
        pending = text.split(whereSeparator: \.isNewline).prefix(2).joined(separator: " ")
        thinking = true; status = "חושב…"; inflight += 1
        Task {
            // Busy/quota/network: retry up to 3 times (2s, 5s, 10s) before giving up on this screen.
            var r: (mode: String, answer: String, cached: Bool)?
            for (n, wait) in [0, 2, 5, 10].enumerated() {
                if wait > 0 { if my == seq { status = "השרת עמוס · מנסה שוב (\(n)/3)" }; try? await Task.sleep(for: .seconds(wait)) }
                r = try? await Task.detached {
                    try await explain(img, text, context: ctx, visualUnit: true) { p in
                        if Reply(p).checking { Task { @MainActor in if my == self.seq { self.status = "בודק שוב…" } } }
                    }
                }.value
                if let a = r?.answer, !Reply(a).kind.isEmpty { break }
                answerCache.removeAll(); r = nil
            }
            inflight -= 1
            done[my] = r.map { (Reply($0.answer), $0.answer, Int(Date().timeIntervalSince(t0) * 1000), text) } ?? nil
            if r == nil, my == seq { status = "אין חיבור לשרת" }
            while let entry = done[nextApply] {
                done[nextApply] = nil
                if let (rep, raw, ms, txt) = entry { apply(rep, raw: raw, ms: ms, replace: replace, latest: nextApply == seq, text: txt) }
                nextApply += 1
            }
            if nextApply > seq { thinking = false }
        }
    }

    func apply(_ r: Reply, raw: String, ms: Int, replace: Bool, latest: Bool = true, text: String = "") {
        if session == nil { session = Session() }
        switch r.kind {
        case "instructions":
            if r["PASSAGE"].lowercased() == "yes", !session!.units.isEmpty {
                session!.units[session!.units.count - 1].passage = String((unit!.passage + "\n" + text).suffix(6000))
                if latest { status = "קטע קריאה נשמר" }
            } else if let u = unit, (!r["NUM"].isEmpty && r["NUM"] == u.num) || (!r["UNIT"].isEmpty && r["UNIT"] == u.title) {
                if latest { instructions = u; current = nil; status = "הנחיות יחידה" }   // same unit intro read again: don't open a new unit
            } else {
                let u = Unit(title: r["UNIT"].isEmpty ? "יחידה" : r["UNIT"], num: r["NUM"], summary: r["SUMMARY"], visual: r["VISUAL"].lowercased() == "yes")
                session!.units.append(u); instructions = u; current = nil; status = "הנחיות יחידה"
            }
        case "question":
            if session!.units.isEmpty { session!.units.append(Unit(title: "כללי", num: "", summary: "", visual: false)) }
            let it = Item(num: r["NUM"], question: r["Q"], answer: r["A"], label: r["ANSWER"], why: r["WHY"], low: r["CONF"].lowercased() == "low", ms: ms, trap: r["TRAP"].isEmpty ? nil : r["TRAP"])
            let ui = session!.units.count - 1
            if let i = session!.units[ui].items.firstIndex(where: { $0.question == it.question || (!it.num.isEmpty && $0.num == it.num) }) {
                session!.units[ui].items[i] = it                         // came back to a question: update, don't duplicate
            } else { session!.units[ui].items.append(it) }
            if latest { current = it; instructions = nil; status = "" }
        case "other":
            if latest { status = "ממתין לשאלה" }
        default:
            if latest { status = String(raw.prefix(120)) }             // server message / error
        }
        save()
    }

    func summaryText() -> String {
        guard let s = session else { return "" }
        var out = "ScreenReader · \(s.start.formatted(date: .abbreviated, time: .shortened))\n"
        for u in s.units {
            out += "\nיחידה \(u.num) · \(u.title)\n"
            for (i, it) in u.items.enumerated() { out += "\(it.num.isEmpty ? String(i + 1) : it.num). \(it.label) · \(it.answer)\(it.low ? " (?)" : "")\(it.trap.map { " · מלכודת: \($0)" } ?? "")\n" }
        }
        return out
    }
}

// MARK: Views
let answerFont = Font.system(size: 44, weight: .semibold)

struct AnswerBlock: View {
    let item: Item; var big: CGFloat = 44; var showWhy = true
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(item.answer.isEmpty ? item.label : item.answer).font(.system(size: big, weight: .semibold)).lineLimit(2).minimumScaleFactor(0.5)
                if item.low { Text("?").font(.system(size: big * 0.45, weight: .semibold)).foregroundStyle(.orange).help("המודל לא בטוח — כדאי לבדוק") }
            }
            if !item.label.isEmpty { Text("תשובה \(item.label)").font(.system(size: big * 0.34, weight: .semibold)).foregroundStyle(Color.accentColor) }
            if showWhy, !item.why.isEmpty { Text(item.why).font(.system(size: 12)).foregroundStyle(.secondary).padding(.top, 6) }
            if let t = item.trap { Text("⚠ מלכודת: \(t)").font(.system(size: showWhy ? 12 : 11)).foregroundStyle(.orange).lineLimit(showWhy ? 3 : 2).padding(.top, showWhy ? 2 : 0) }
        }
    }
}

struct SourceMenu: View {
    @ObservedObject var m: Model
    var body: some View {
        Menu {
            Button("כל המסך") { m.setSource(.screen) }
            Button("סמן אזור…") { m.pickRegion() }
            Divider()
            Section("חלון מסוים") {
                ForEach(Array(m.windows.enumerated()), id: \.offset) { _, w in
                    Button(w.name) { m.setSource(.window(bundleID: w.bundleID, windowID: w.windowID, name: w.name)) }
                }
            }
        } label: { Label(m.sourceLabel, systemImage: "macwindow") }
        .menuStyle(.borderlessButton).fixedSize()
        .simultaneousGesture(TapGesture().onEnded { m.loadWindows() })
        .help("מה האפליקציה קוראת")
    }
}

struct MainView: View {
    @ObservedObject var m: Model
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                if m.phase != .idle { Circle().fill(m.phase == .running ? .red : .orange).frame(width: 7, height: 7) }
                if m.inflight > 1 { Text("+\(m.inflight - 1)").font(.system(size: 11)).foregroundStyle(.secondary).help("עונה גם על שאלות קודמות") }
                Spacer()
                SourceMenu(m: m)
                Button { m.showList.toggle() } label: { Image(systemName: "sidebar.right") }.help("רשימת השאלות (⌥⌘L)")
                Button { m.newSession() } label: { Image(systemName: "arrow.counterclockwise") }.help("סשן חדש: איפוס (הקודם נשמר)")
                Button { m.onFloat?() } label: { Image(systemName: "pip.enter") }.help("חלון צף (⌥⌘M)")
                Button { m.startStop() } label: {
                    Label(m.phase == .idle ? "התחל" : "סיים", systemImage: m.phase == .idle ? "play.fill" : "stop.fill")
                }
                .keyboardShortcut(.return, modifiers: .command)
                .buttonStyle(.borderedProminent).tint(m.phase == .idle ? .accentColor : .red)
                .help("⌥⌘S")
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            Divider()
            HStack(spacing: 0) {
                if m.showList { Sidebar(m: m).frame(width: 210); Divider() }
                Center(m: m).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: m.showList ? 560 : 320, minHeight: 300)
        .environment(\.layoutDirection, .rightToLeft)
        .sheet(isPresented: $m.showSummary) { SummaryView(m: m) }
        .onAppear { m.loadWindows() }
    }
}

struct Sidebar: View {
    @ObservedObject var m: Model
    var body: some View {
        List {
            if let s = m.session {
                ForEach(s.units) { u in
                    Section("\(u.num.isEmpty ? "" : "יחידה \(u.num) · ")\(u.title)") {
                        ForEach(Array(u.items.enumerated()), id: \.element.id) { i, it in
                            HStack {
                                Text("\(it.num.isEmpty ? String(i + 1) : it.num) · \(it.label)").monospacedDigit()
                                Spacer()
                                if it.trap != nil { Text("⚠").foregroundStyle(.orange) }
                                if it.low { Text("?").foregroundStyle(.orange) }
                            }
                            .contentShape(Rectangle())
                            .onTapGesture { m.current = it; m.instructions = nil }
                            .listRowBackground(m.current?.id == it.id ? Color.accentColor.opacity(0.15) : nil)
                        }
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .overlay { if m.session?.units.isEmpty ?? true { Text("השאלות יופיעו כאן").font(.callout).foregroundStyle(.tertiary) } }
    }
}

struct Center: View {
    @ObservedObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if m.needsPermission {
                Empty(icon: "lock.shield", title: "צריך הרשאת הקלטת מסך",
                      text: "הפעל את ScreenReader ברשימה, ואז סגור ופתח את האפליקציה.",
                      action: ("פתח הגדרות", { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!) }))
            } else if m.phase == .idle && m.current == nil {
                if !m.hasChosenSource {
                    Empty(icon: "macwindow", title: "מה לקרוא?", text: "בחר את חלון הסימולטור מהתפריט למעלה, ואז לחץ התחל.", action: nil)
                } else {
                    Empty(icon: "play.circle", title: "מוכן", text: "פתח את הסימולטור ולחץ התחל (⌥⌘S).", action: nil)
                }
            } else if let u = m.instructions {
                Label("הנחיות יחידה", systemImage: "book").font(.system(size: 12, weight: .medium)).foregroundStyle(.purple)
                Text("\(u.num.isEmpty ? "" : "יחידה \(u.num) · ")\(u.title)").font(.system(size: 26, weight: .semibold)).padding(.top, 12)
                Text(u.summary).font(.system(size: 14)).foregroundStyle(.secondary).padding(.top, 6)
                Spacer()
                if u.visual { Label("ביחידה הזו נשלחת תמונה עם כל שאלה", systemImage: "photo").font(.system(size: 12)).foregroundStyle(.secondary) }
            } else {
                if let u = m.unit {
                    Text("\(u.num.isEmpty ? "" : "יחידה \(u.num) · ")\(u.title)\(m.current?.num.isEmpty == false ? " · שאלה \(m.current!.num)" : "")")
                        .font(.system(size: 12, weight: .medium)).foregroundStyle(Color.accentColor)
                }
                Text(m.thinking ? m.pending : (m.current?.question ?? "")).font(.system(size: 15)).lineLimit(3).padding(.top, 10)
                Group {
                    if m.thinking { Text("• • •").font(answerFont).foregroundStyle(.tertiary) }
                    else if let it = m.current { AnswerBlock(item: it) }
                }.padding(.top, 20)
                Spacer()
            }
            if !m.status.isEmpty && !m.needsPermission {
                HStack { Text(m.status).font(.system(size: 11)).foregroundStyle(.secondary); Spacer()
                    if let it = m.current, !m.thinking { Text(String(format: "%.1f שנ׳", Double(it.ms) / 1000)).font(.system(size: 11)).foregroundStyle(.tertiary) } }
                .padding(.top, 8)
            }
        }
        .padding(.horizontal, 28).padding(.vertical, 22)
    }
}

struct Empty: View {
    let icon: String, title: String, text: String; let action: (String, () -> Void)?
    var body: some View {
        VStack(spacing: 10) {
            Spacer()
            Image(systemName: icon).font(.system(size: 34)).foregroundStyle(.tertiary)
            Text(title).font(.system(size: 17, weight: .semibold))
            Text(text).font(.system(size: 13)).foregroundStyle(.secondary).multilineTextAlignment(.center)
            if let a = action { Button(a.0, action: a.1).padding(.top, 4) }
            Spacer()
        }.frame(maxWidth: .infinity)
    }
}

// Floating card and the narrow main window show the same thing: where we are, the answer, the option.
struct MiniView: View {
    @ObservedObject var m: Model
    var onExpand: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Circle().fill(m.phase == .running ? .red : .orange).frame(width: 6, height: 6)
                Text(miniTitle).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Button(action: onExpand) { Image(systemName: "arrow.up.left.and.arrow.down.right") }.buttonStyle(.plain).foregroundStyle(.secondary).help("חלון מלא (⌥⌘M)")
            }
            if m.thinking { Text("• • •").font(.system(size: 28, weight: .semibold)).foregroundStyle(.tertiary) }
            else if let u = m.instructions { Text(u.title).font(.system(size: 20, weight: .semibold)); Text("הנחיות יחידה").font(.system(size: 11)).foregroundStyle(.purple) }
            else if let it = m.current { AnswerBlock(item: it, big: 28, showWhy: false) }
            else { Text(m.status.isEmpty ? "מוכן" : m.status).font(.system(size: 13)).foregroundStyle(.secondary) }
        }
        .padding(12).frame(width: 220, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .environment(\.layoutDirection, .rightToLeft)
    }
    var miniTitle: String {
        let u = m.unit.map { "\($0.num.isEmpty ? "" : "יחידה \($0.num) · ")\($0.title)" } ?? m.sourceLabel
        return u + (m.current?.num.isEmpty == false ? " · שאלה \(m.current!.num)" : "")
    }
}

struct SummaryView: View {
    @ObservedObject var m: Model
    @Environment(\.dismiss) var dismiss
    var body: some View {
        let s = m.session ?? Session()
        let items = s.units.flatMap(\.items)
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("סיכום סשן").font(.system(size: 17, weight: .semibold)); Spacer()
                Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(m.summaryText(), forType: .string) } label: { Label("העתק", systemImage: "doc.on.doc") }
                Button { NSWorkspace.shared.open(sessionsDir) } label: { Label("סשנים קודמים", systemImage: "folder") }
                Button("סגור") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            HStack(spacing: 10) {
                Stat(title: "שאלות", value: "\(items.count)")
                Stat(title: "זמן כולל", value: Duration.seconds((s.end ?? Date()).timeIntervalSince(s.start)).formatted(.time(pattern: .hourMinuteSecond)))
                Stat(title: "ממוצע לתשובה", value: items.isEmpty ? "—" : String(format: "%.1f שנ׳", Double(items.map(\.ms).reduce(0, +)) / Double(items.count) / 1000))
                Stat(title: "לבדיקה (?)", value: "\(items.filter(\.low).count)", tint: .orange)
                Stat(title: "מלכודות", value: "\(items.filter { $0.trap != nil }.count)", tint: .orange)
            }
            List {
                ForEach(s.units) { u in
                    DisclosureGroup {
                        ForEach(Array(u.items.enumerated()), id: \.element.id) { i, it in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack { Text("\(it.num.isEmpty ? String(i + 1) : it.num). \(it.label) · \(it.answer)"); Spacer(); if it.low { Text("?").foregroundStyle(.orange) } }
                                if let t = it.trap { Text("⚠ מלכודת: \(t)").font(.system(size: 11)).foregroundStyle(.orange) }
                            }
                                .help(it.question)
                        }
                    } label: {
                        HStack { Text("\(u.num.isEmpty ? "" : "יחידה \(u.num) · ")\(u.title)").fontWeight(.medium); Spacer()
                            Text("\(u.items.count) שאלות").foregroundStyle(.secondary)
                            if u.items.contains(where: \.low) { Text("· ? \(u.items.filter(\.low).count)").foregroundStyle(.orange) } }
                    }
                }
            }
            .listStyle(.inset)
        }
        .padding(20).frame(width: 640, height: 500)
        .environment(\.layoutDirection, .rightToLeft)
    }
}

struct Stat: View {
    let title: String, value: String; var tint: Color = .primary
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 11)).foregroundStyle(.secondary)
            Text(value).font(.system(size: 20, weight: .semibold)).foregroundStyle(tint).monospacedDigit()
        }.padding(10).frame(maxWidth: .infinity, alignment: .leading).background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: Global shortcuts (⌥⌘ + S/P/R/M) — Carbon hotkeys, work while the simulator has focus, no extra permission.
nonisolated(unsafe) var hotkeyActions: [UInt32: @MainActor () -> Void] = [:]
nonisolated(unsafe) var hotkeyRefs: [EventHotKeyRef?] = []
@MainActor func registerHotkeys(_ map: [(Int, @MainActor () -> Void)]) {
    var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
    InstallEventHandler(GetApplicationEventTarget(), { _, ev, _ in
        var hk = EventHotKeyID()
        GetEventParameter(ev, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
        let id = hk.id
        DispatchQueue.main.async { MainActor.assumeIsolated { hotkeyActions[id]?() } }
        return noErr
    }, 1, &spec, nil, nil)
    for (i, (key, action)) in map.enumerated() {
        var ref: EventHotKeyRef?
        RegisterEventHotKey(UInt32(key), UInt32(optionKey | cmdKey), EventHotKeyID(signature: OSType(0x53524452), id: UInt32(i + 1)), GetApplicationEventTarget(), 0, &ref)
        hotkeyRefs.append(ref); hotkeyActions[UInt32(i + 1)] = action
    }
}

// MARK: App — normal window (resize / full screen) + floating card over the simulator.
@MainActor final class App: NSObject, NSApplicationDelegate {
    let m = Model()
    var window: NSWindow!
    var panel: NSPanel!

    func applicationDidFinishLaunching(_ n: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 470),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "ScreenReader"; window.titleVisibility = .hidden
        window.contentView = NSHostingView(rootView: MainView(m: m))
        window.center(); window.setFrameAutosaveName("main"); window.collectionBehavior = [.fullScreenPrimary]
        window.makeKeyAndOrderFront(nil)

        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 220, height: 130), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating; panel.isFloatingPanel = true; panel.isMovableByWindowBackground = true
        panel.backgroundColor = .clear; panel.isOpaque = false; panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]   // floats over a full-screen simulator
        let host = NSHostingView(rootView: MiniView(m: m, onExpand: { [weak self] in self?.toggleFloat() }))
        host.sizingOptions = [.intrinsicContentSize]
        panel.contentView = host
        panel.setFrameAutosaveName("mini")
        if panel.frame.origin == .zero, let v = NSScreen.main?.visibleFrame { panel.setFrameTopLeftPoint(NSPoint(x: v.minX + 20, y: v.maxY - 20)) }
        m.onFloat = { [weak self] in self?.toggleFloat() }

        registerHotkeys([
            (kVK_ANSI_S, { [weak self] in self?.m.startStop() }),
            (kVK_ANSI_P, { [weak self] in self?.m.pauseResume() }),
            (kVK_ANSI_R, { [weak self] in self?.m.askAgain() }),
            (kVK_ANSI_M, { [weak self] in self?.toggleFloat() }),
            (kVK_ANSI_L, { [weak self] in self?.m.showList.toggle() }),
        ])
        buildMenu()
        NSApp.activate(ignoringOtherApps: true)
    }

    func toggleFloat() {
        if panel.isVisible { panel.orderOut(nil); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
        else { panel.orderFrontRegardless(); window.orderOut(nil) }
    }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let am = NSMenu(); appItem.submenu = am
        am.addItem(withTitle: "יציאה מ־ScreenReader", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let sItem = NSMenuItem(); main.addItem(sItem)
        let sm = NSMenu(title: "סשן"); sItem.submenu = sm
        for (t, sel, k) in [("התחל / סיים  ⌥⌘S", #selector(mStart), ""), ("השהה / המשך  ⌥⌘P", #selector(mPause), ""),
                            ("שאל שוב  ⌥⌘R", #selector(mAgain), ""), ("חלון צף  ⌥⌘M", #selector(mFloat), ""), ("סיכום", #selector(mSummary), ""),
                            ("סשן חדש (איפוס)", #selector(mNew), "n"), ("פתח סשנים קודמים", #selector(mFolder), "")] {
            let i = NSMenuItem(title: t, action: sel, keyEquivalent: k); i.target = self; sm.addItem(i)
        }
        let wItem = NSMenuItem(); main.addItem(wItem)
        let wm = NSMenu(title: "Window"); wItem.submenu = wm
        wm.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        wm.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        let eItem = NSMenuItem(); main.insertItem(eItem, at: 1)
        let em = NSMenu(title: "Edit"); eItem.submenu = em
        em.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        NSApp.mainMenu = main; NSApp.windowsMenu = wm
    }
    @objc func mStart() { m.startStop() }
    @objc func mPause() { m.pauseResume() }
    @objc func mAgain() { m.askAgain() }
    @objc func mFloat() { toggleFloat() }
    @objc func mNew() { m.newSession() }
    @objc func mFolder() { NSWorkspace.shared.open(sessionsDir) }
    @objc func mSummary() { if m.session != nil { window.makeKeyAndOrderFront(nil); m.showSummary = true } }

    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool { window.makeKeyAndOrderFront(nil); return true }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ n: Notification) { m.save() }
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
if args.count >= 3, args[1] == "--run-sim" {
    // Feed screenshots in order (instructions + questions) through OCR -> server with unit context, like the app.
    // Prints "<file> KIND ANSWER" per screen; test/sim5/score.py compares with key.json.
    let sem = DispatchSemaphore(value: 0)
    Task {
        var ctx = ""
        for path in args[2...] {
            let img = loadImage(path), text = normalize((try? ocr(img)) ?? "")
            let r = try? await explain(img, text, context: ctx, visualUnit: true)
            let rep = Reply(r?.answer ?? "")
            if rep.kind == "instructions" { ctx = "Unit \(rep["NUM"]) \(rep["UNIT"]): \(rep["SUMMARY"])" }
            print("\((path as NSString).lastPathComponent)\t\(rep.kind.isEmpty ? "error" : rep.kind)\t\(rep["ANSWER"])\t\(rep["CONF"])")
            fflush(stdout)
        }
        sem.signal()
    }
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
app.setActivationPolicy(.regular)
let delegate = MainActor.assumeIsolated { App() }
app.delegate = delegate
app.run()
