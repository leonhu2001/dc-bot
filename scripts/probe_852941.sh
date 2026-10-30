#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
TARGET="${1:-https://app.852941.xyz/}"
OUTPUT="${2:-/tmp/market_source_probe_852941.json}"

cd "$APP"

if [ -x "$APP/venv/bin/python" ]; then
    PYTHON="$APP/venv/bin/python"
elif [ -x "$APP/.venv/bin/python" ]; then
    PYTHON="$APP/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "ERROR: Python executable not found." >&2
    exit 2
fi

echo "=== PUBLIC MARKET SOURCE PROBE ==="
echo "Target: $TARGET"
echo "Mode:   public GET-only discovery"
echo "Output: $OUTPUT"
echo

"$PYTHON" tools/probe_public_market_source.py --target "$TARGET" --output "$OUTPUT"

echo
echo "PROBE COMPLETED"
echo "Candidate URLs are discovery-only and were not invoked."
