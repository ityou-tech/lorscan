#!/usr/bin/env bash
# One-shot installer for running lorscan as a LaunchAgent on a Mac (Apple Silicon recommended).
#
#   ./deploy/macmini/install.sh           # full install: sync, bootstrap, install service
#   ./deploy/macmini/install.sh --no-data # skip sync-catalog + index-images (already done)
#
# Idempotent: re-running reinstalls the LaunchAgent cleanly.

set -euo pipefail

skip_data=0
if [ "${1:-}" = "--no-data" ]; then
    skip_data=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
    echo "error: uv not found in PATH." >&2
    echo "  install with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

LABEL="tech.ityou.lorscan"
PLIST_NAME="$LABEL.plist"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
PLIST_DEST="$LAUNCH_AGENT_DIR/$PLIST_NAME"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.template"
SERVICE_TARGET="gui/$(id -u)/$LABEL"
DOMAIN_TARGET="gui/$(id -u)"

mkdir -p "$LAUNCH_AGENT_DIR" "$LOG_DIR"

echo "[1/4] uv sync"
cd "$REPO_ROOT"
"$UV" sync

if [ "$skip_data" -eq 0 ]; then
    echo "[2/4] Bootstrapping catalog + embeddings (a few minutes on Apple Silicon, longer on Intel)..."
    "$UV" run lorscan sync-catalog
    "$UV" run lorscan index-images
else
    echo "[2/4] Skipping data bootstrap (--no-data)"
fi

echo "[3/4] Writing LaunchAgent to $PLIST_DEST"
sed -e "s|__UV_PATH__|$UV|g" \
    -e "s|__REPO_PATH__|$REPO_ROOT|g" \
    -e "s|__LOG_PATH__|$LOG_DIR|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

echo "[4/4] Loading service"
# launchctl bootstrap fails if the service is already loaded; bootout it
# first so this script is idempotent.
if launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
    launchctl bootout "$DOMAIN_TARGET" "$PLIST_DEST" || true
fi
launchctl bootstrap "$DOMAIN_TARGET" "$PLIST_DEST"
launchctl enable "$SERVICE_TARGET"

# Resolve the network hostname so we can print a working LAN URL.
hostname_local="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"

cat <<EOF

  lorscan is running.

    local:    http://localhost:8000
    network:  http://${hostname_local}.local:8000

  logs:    $LOG_DIR/lorscan.out.log
           $LOG_DIR/lorscan.err.log

  status:  launchctl print $SERVICE_TARGET | head
  stop:    launchctl bootout $DOMAIN_TARGET $PLIST_DEST
  start:   launchctl bootstrap $DOMAIN_TARGET $PLIST_DEST

  See docs/deploy/macmini.md for sleep + firewall settings.

EOF
