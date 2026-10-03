#!/bin/bash
# Build ScreenReader.app (needs Xcode Command Line Tools: xcode-select --install)
set -e
cd "$(dirname "$0")"
APP=ScreenReader.app
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
# Server defaults baked in (CI passes them from repo secrets); empty = read ~/.config/screenreader/server
printf 'let defaultServer = "%s"\nlet defaultToken = "%s"\n' "${SR_SERVER:-}" "${SR_TOKEN:-}" > Config.swift
ARCH=${ARCH:-$(uname -m)}
swiftc -O -target "$ARCH-apple-macos14.0" main.swift Config.swift -o "$APP/Contents/MacOS/ScreenReader"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.screenreader</string>
<key>CFBundleName</key><string>ScreenReader</string>
<key>CFBundleExecutable</key><string>ScreenReader</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>
<key>NSScreenCaptureUsageDescription</key><string>Reads visible text locally with Apple Vision.</string>
</dict></plist>
P
# Stable designated requirement so the Screen Recording grant survives rebuilds
codesign --force -s - -r='designated => identifier "local.screenreader"' "$APP"
echo "Built $APP"
