#!/bin/bash
# Automated OCR check: renders test/cases.html to PNG via headless Chrome (or uses a screenshot you pass), then OCRs it.
set -e; cd "$(dirname "$0")/.."
[ -x ScreenReader.app/Contents/MacOS/ScreenReader ] || ./build.sh
IMG=${1:-/tmp/sr-cases.png}
if [ -z "$1" ]; then
  :
fi
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -z "$1" ]; then
  CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  if [ -x "$CH" ]; then "$CH" --headless --disable-gpu --window-size=1000,1100 --screenshot="$IMG" "file://$PWD/test/cases.html" 2>/dev/null
  else screencapture -x "$IMG"; echo "(no Chrome: used full-screen screenshot — open test/cases.html first)"; fi
fi
OUT=$(ScreenReader.app/Contents/MacOS/ScreenReader --selftest "$IMG"); rm -f "$IMG"
echo "$OUT"; echo "---- checks"
pass=0; fail=0
for s in "quick brown fox" "שלום עולם" "Google" "Jupiter" "12.5%" "1,299.99" "37%"; do
  if grep -qF "$s" <<<"$OUT"; then echo "PASS  $s"; pass=$((pass+1)); else echo "FAIL  $s"; fail=$((fail+1)); fi
done
grep -q "self-diff: 0.0" <<<"$OUT" && echo "PASS  identical frame -> diff 0 (OCR skipped)" || { echo "FAIL  dedupe"; fail=$((fail+1)); }
# Practice layout: text page -> TEXT, shape/matrix pages -> VISUAL (no network)
D=$(mktemp -d)
for f in cases q-text q-shapes q-matrix; do
  if [ -x "$CH" ]; then "$CH" --headless --disable-gpu --window-size=1000,1100 --screenshot="$D/$f.png" "file://$PWD/test/$f.html" 2>/dev/null; fi
done
if [ -f "$D/q-text.png" ]; then
  L=$(ScreenReader.app/Contents/MacOS/ScreenReader --layout "$D"/*.png); echo "$L"
  for e in "cases.png TEXT" "q-text.png TEXT" "q-shapes.png VISUAL" "q-matrix.png VISUAL"; do
    if grep -qF "$e" <<<"$L"; then echo "PASS  $e"; pass=$((pass+1)); else echo "FAIL  $e"; fail=$((fail+1)); fi
  done
else echo "SKIP  layout checks (need Chrome)"; fi
rm -rf "$D"
echo "pass=$pass fail=$fail"
