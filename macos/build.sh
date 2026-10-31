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
APP=build/Share.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/ShareApp "$APP/Contents/MacOS/Share"
cp Info.plist "$APP/Contents/Info.plist"
if [ -n "${VERSION:-}" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist"
fi
# ad-hoc signature: enough to run locally and to register the URL scheme
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
