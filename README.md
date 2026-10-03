# ScreenReader (macOS 14+)
Small floating window that passively reads on-screen text (Hebrew + English) using Apple Vision, locally.

**Run:** `./run.sh` (first time builds; needs `xcode-select --install`). Press **Start**.
First start asks for Screen Recording: System Settings → Privacy & Security → Screen & System Audio Recording → enable **ScreenReader**, quit and reopen.

**Test:** `./test/run-tests.sh`

## Architecture
Timer every 1.5 s → ScreenCaptureKit screenshot of the main display (in memory, own window excluded) → 64×36 grayscale fingerprint → if unchanged, skip → else Vision OCR (`he-IL`,`en-US`, accurate) → whitespace normalize → update window only if text differs.
Nothing is written to disk or sent over the network. The app never clicks or types.

## Practice mode (Explain button)
On click: layout check on the last frame (connected ink blobs; blobs > 2.5x median glyph height = graphics, plain rectangular frames ignored).
TEXT -> OCR text only. VISUAL/MIXED -> cropped PNG of graphics + nearby text (<=1568px, in memory) + OCR text.
Sent to the server proxy (`server/proxy.py`, systemd `screenreader-proxy`, port 8099), which asks Gemini Flash and streams the answer back. Model key lives only on the server (`~/.config/screenreader/llm_key`). Same question twice -> cached answer, no new request.

## Download
GitHub Actions builds on every push to main and publishes `ScreenReader.zip` under Releases → latest. Server URL + token come from repo secrets `SR_SERVER` / `SR_TOKEN`. First open: right-click → Open (unsigned).

## Decisions / licenses
- Reviewed screenpipe (heavy: Rust + DB + recording, MIT), macvision / mac-screen-vision (CLI Vision OCR wrappers). Not reused — the needed part is ~20 lines of Vision API calls. No third-party code, no dependencies.
- Apple Vision has no Hebrew on this macOS, so OCR uses Tesseract (`brew install tesseract tesseract-lang`, Apache-2.0) via stdin pipe when installed; falls back to Vision otherwise.
- Accessibility API skipped: browsers expose text unevenly and it needs a second permission; OCR + change gate is already cheap.
