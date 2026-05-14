#!/usr/bin/env bash
# Installs the newsline daily LaunchAgent.
#
# What it does:
#   1. Substitutes your $HOME, project dir, and uv path into the plist template.
#   2. Drops the rendered plist into ~/Library/LaunchAgents/.
#   3. Loads it with `launchctl bootstrap`.
#
# Idempotent — re-running updates the plist and reloads cleanly.
# Uninstall: ./scripts/install-daemon.sh --uninstall

set -euo pipefail

LABEL="com.newsline.daily"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="${PROJECT_DIR}/scripts/launchd/${LABEL}.plist.template"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

uninstall() {
    if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
        echo "→ bootout ${LABEL}"
        launchctl bootout "${DOMAIN}/${LABEL}" || true
    fi
    if [[ -f "${TARGET}" ]]; then
        echo "→ rm ${TARGET}"
        rm "${TARGET}"
    fi
    echo "✓ Uninstalled ${LABEL}"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

UV_PATH="$(command -v uv)"
if [[ -z "${UV_PATH}" ]]; then
    echo "ERROR: 'uv' not found in PATH. Install uv first." >&2
    exit 1
fi

mkdir -p "$(dirname "${TARGET}")" "${HOME}/Library/Logs"

# Render plist with absolute paths (launchd doesn't expand env vars in keys).
sed \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__UV_PATH__|${UV_PATH}|g" \
    "${TEMPLATE}" > "${TARGET}"

# Reload cleanly. bootstrap will fail if already loaded; bootout first.
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${DOMAIN}/${LABEL}" || true
fi
launchctl bootstrap "${DOMAIN}" "${TARGET}"
launchctl enable "${DOMAIN}/${LABEL}"

cat <<EOF
✓ Installed ${LABEL}
  plist     ${TARGET}
  schedule  daily at 07:00 local time
  log       ${HOME}/Library/Logs/newsline.log

To run once now:  launchctl kickstart -k ${DOMAIN}/${LABEL}
To inspect:       launchctl print ${DOMAIN}/${LABEL}
To uninstall:     ${PROJECT_DIR}/scripts/install-daemon.sh --uninstall
EOF
