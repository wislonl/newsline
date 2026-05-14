#!/usr/bin/env bash
# Build a real macOS .app bundle from the SwiftPM executable.
#
# Output: apps/macos/build/Newsline.app
#
# This is reproducible without Xcode — we just place the release binary
# in a hand-rolled bundle layout and write Info.plist with the right keys
# so LaunchServices treats it as a foreground GUI app.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MACOS_DIR="${PROJECT_DIR}/apps/macos"
BUILD_DIR="${MACOS_DIR}/build"
APP_DIR="${BUILD_DIR}/Newsline.app"
VERSION="$(git -C "${PROJECT_DIR}" rev-parse --short HEAD 2>/dev/null || echo dev)"

echo "→ Building Swift release binary"
(cd "${MACOS_DIR}" && swift build -c release)

BIN="$(cd "${MACOS_DIR}" && swift build -c release --show-bin-path)/Newsline"
if [[ ! -x "${BIN}" ]]; then
    echo "ERROR: release binary not found at ${BIN}" >&2
    exit 1
fi

echo "→ Assembling ${APP_DIR}"
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS" "${APP_DIR}/Contents/Resources"

cp "${BIN}" "${APP_DIR}/Contents/MacOS/Newsline"

sed "s|__VERSION__|${VERSION}|g" \
    "${MACOS_DIR}/Info.plist.template" \
    > "${APP_DIR}/Contents/Info.plist"

plutil -lint "${APP_DIR}/Contents/Info.plist" >/dev/null

# Refresh LaunchServices so Spotlight/Finder pick up the new bundle.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "${APP_DIR}" 2>/dev/null || true

cat <<EOF
✓ Built ${APP_DIR}
  version  ${VERSION}
  size     $(du -sh "${APP_DIR}" | cut -f1)

Open it:           open "${APP_DIR}"
Install to Apps:   ${PROJECT_DIR}/scripts/install-app.sh
EOF
