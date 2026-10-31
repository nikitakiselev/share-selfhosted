#!/bin/sh
# Builds Share.app into macos/build. Usage: ./build.sh [install]
# "install" also copies it to /Applications and launches it.
set -eu
cd "$(dirname "$0")"
# SwiftUI macros (@State and friends) ship only with Xcode's toolchain, not the Command Line Tools
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
swift build -c release 2>&1 | grep -v "ld: warning: search path" || true
test -x .build/release/ShareApp
APP=build/Share.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/ShareApp "$APP/Contents/MacOS/Share"
cp Info.plist "$APP/Contents/Info.plist"
# ad-hoc signature: enough to run locally and to register the URL scheme
codesign --force --sign - "$APP" >/dev/null
echo "built $APP"
if [ "${1:-}" = "install" ]; then
  pkill -x Share 2>/dev/null || true
  rm -rf /Applications/Share.app
  cp -R "$APP" /Applications/Share.app
  open /Applications/Share.app
  echo "installed /Applications/Share.app"
fi
