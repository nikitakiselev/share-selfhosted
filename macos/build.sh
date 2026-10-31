#!/bin/sh
# Builds Share.app (and Share-<version>.zip) into macos/build. Usage: [VERSION=1.2.3] ./build.sh [install]
# "install" also copies it to /Applications and launches it.
set -eu
cd "$(dirname "$0")"
# SwiftUI macros (@State and friends) ship only with Xcode's toolchain, not the Command Line Tools
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
swift build -c release 2>&1 | grep -v "ld: warning: search path" || true
test -x .build/release/ShareApp
test -x .build/release/ShareExtension
APP=build/Share.app
EXT="$APP/Contents/PlugIns/ShareExtension.appex"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$EXT/Contents/MacOS"
cp .build/release/ShareApp "$APP/Contents/MacOS/Share"
cp Info.plist "$APP/Contents/Info.plist"
cp Icons/MenuBarIcon.svg "$APP/Contents/Resources/"
# the app icon (Dock, Finder, the share menu) from Icons/AppIcon.png, when it exists
if [ -f Icons/AppIcon.png ]; then
  ICONSET=build/AppIcon.iconset
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z $size $size Icons/AppIcon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size*2)) $((size*2)) Icons/AppIcon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
  rm -rf "$ICONSET"
fi
cp .build/release/ShareExtension "$EXT/Contents/MacOS/ShareExtension"
cp ShareExtension-Info.plist "$EXT/Contents/Info.plist"
if [ -n "${VERSION:-}" ]; then
  for plist in "$APP/Contents/Info.plist" "$EXT/Contents/Info.plist"; do
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$plist"
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$plist"
  done
fi
# ad-hoc signatures: enough to run locally, to register the URL scheme and the share extension
codesign --force --sign - --entitlements ShareExtension.entitlements "$EXT" >/dev/null
codesign --force --sign - "$APP" >/dev/null
ditto -c -k --keepParent "$APP" "build/Share-${VERSION:-dev}.zip"
echo "built $APP, build/Share-${VERSION:-dev}.zip"
if [ "${1:-}" = "install" ]; then
  pkill -x Share 2>/dev/null || true
  rm -rf /Applications/Share.app
  cp -R "$APP" /Applications/Share.app
  open /Applications/Share.app
  echo "installed /Applications/Share.app"
fi
