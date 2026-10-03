# TODO
## Completed
- Single-file native app (Swift/AppKit/ScreenCaptureKit/Vision), build + run scripts, change gate, Copy, Start/Pause, status, stats line
- Automated OCR test (test/run-tests.sh) + manual test page (test/cases.html)
## Current
- First build + test on Elia's Mac (written on Linux — not yet compiled)
- Practice mode: Explain button sends current OCR text to Claude (claude-opus-5-5), shows answer + short explanation. Uses logged-in Claude Code CLI (`claude -p`, subscription) by default; API key (~/.config/screenreader/anthropic_key or ANTHROPIC_API_KEY) overrides. Panel is visible in screen sharing.
- Visual questions: auto TEXT/VISUAL detection + crop; tests q-text, q-shapes, q-matrix
## Next
- Region selection (currently whole main display)
- Optional AX text path
## Blockers
- Needs a Mac to compile/test
