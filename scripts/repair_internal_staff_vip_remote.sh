#!/usr/bin/env bash
# VPS-side runner. No commands or arguments are ever piped from Windows.
set -Eeuo pipefail
cd /opt/dc-bot

PYTHON="$PWD/venv/bin/python"
AUDIT="$PWD/scripts/repair_internal_staff_vip_20261119.py"
test -x "$PYTHON"
test -f "$AUDIT"

echo "=== VIP-ONLY PRE-APPLY CHECK (NO DATABASE WRITES) ==="
"$PYTHON" "$AUDIT" --vip-only --check-apply

# Snapshot the running services, then restart only those we actually stopped.
# The market worker can share the project database, so include it in the pause.
SERVICES=(dc-bot.service dc-bot-dashboard.service dc-bot-market.service)
RUNNING=()
for service in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$service"; then
        RUNNING+=("$service")
    fi
done

restore() {
    local status=$?
    trap - EXIT
    echo "=== RESTORE PREVIOUS SERVICE STATES ==="
    for service in "${RUNNING[@]}"; do
        if ! systemctl start "$service"; then
            echo "ERROR: failed to start $service" >&2
            status=1
        fi
    done
    exit "$status"
}
trap restore EXIT

for service in "${RUNNING[@]}"; do
    echo "Stopping $service"
    systemctl stop "$service"
done

echo "=== APPLY VERIFIED VIP-ONLY REVERSAL (AUTO DB BACKUP) ==="
"$PYTHON" "$AUDIT" --vip-only --apply
