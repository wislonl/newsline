#!/usr/bin/env bash
# Install (or refresh) the Newsline.app symlink in ~/Applications.
#
# Uses a symlink so `news app build` rebuilds in place — no need to
# re-copy the bundle. The symlink target lives in the repo.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${PROJECT_DIR}/apps/macos/build/Newsline.app"
DEST_DIR="${HOME}/Applications"
DEST="${DEST_DIR}/Newsline.app"

if [[ ! -d "${SRC}" ]]; then
    echo "→ ${SRC} doesn't exist yet; building first..."
    "${PROJECT_DIR}/scripts/build-app.sh"
fi

mkdir -p "${DEST_DIR}"

# Remove an existing entry whether it's a symlink or a real bundle.
if [[ -e "${DEST}" || -L "${DEST}" ]]; then
    rm -rf "${DEST}"
fi

ln -s "${SRC}" "${DEST}"
echo "✓ Linked ${DEST} -> ${SRC}"
echo "  Open with: open -a Newsline"
