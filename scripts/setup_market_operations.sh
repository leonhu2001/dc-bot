#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
BACKUP_DIR="$APP/_archive/market_db"
BACKUP_SERVICE="dc-bot-market-backup.service"
BACKUP_TIMER="dc-bot-market-backup.timer"
HEALTH_SERVICE="dc-bot-market-health.service"
HEALTH_TIMER="dc-bot-market-health.timer"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: market operations setup must run as root."
    exit 2
fi

cd "$APP"

required=(
    "scripts/market_backup.py"
    "scripts/market_health_probe.py"
    "$BACKUP_SERVICE"
    "$BACKUP_TIMER"
    "$HEALTH_SERVICE"
    "$HEALTH_TIMER"
    "web/.env"
)
for path in "${required[@]}"; do
    if [ ! -f "$APP/$path" ]; then
        echo "ERROR: missing $APP/$path"
        exit 2
    fi
done

if ! command -v pg_dump >/dev/null 2>&1 || ! command -v pg_restore >/dev/null 2>&1; then
    echo "ERROR: pg_dump and pg_restore are required for Market backups."
    exit 2
fi

mkdir -p "$BACKUP_DIR"
chown dc-bot-web:dc-bot-web "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

echo "Installing Market operations systemd units..."
for unit in "$BACKUP_SERVICE" "$BACKUP_TIMER" "$HEALTH_SERVICE" "$HEALTH_TIMER"; do
    install -m 0644 "$APP/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now "$BACKUP_TIMER" "$HEALTH_TIMER" >/dev/null

echo "Running initial PostgreSQL backup..."
systemctl start "$BACKUP_SERVICE"
systemctl is-failed --quiet "$BACKUP_SERVICE" && {
    systemctl status "$BACKUP_SERVICE" --no-pager || true
    journalctl -u "$BACKUP_SERVICE" -n 80 --no-pager || true
    echo "ERROR: initial Market backup failed."
    exit 1
}

echo "Running production Market health probe..."
if ! systemctl start "$HEALTH_SERVICE"; then
    systemctl status "$HEALTH_SERVICE" --no-pager || true
    journalctl -u "$HEALTH_SERVICE" -n 80 --no-pager || true
    echo "ERROR: Market health probe failed."
    echo "If web_push_enabled=false, run scripts/setup_web_push_production.ps1 and rerun this setup."
    exit 1
fi

BACKUP_NEXT="$(systemctl show "$BACKUP_TIMER" -p NextElapseUSecRealtime --value || true)"
HEALTH_NEXT="$(systemctl show "$HEALTH_TIMER" -p NextElapseUSecRealtime --value || true)"

echo "PASS: Market PostgreSQL backup timer enabled"
echo "PASS: Market health probe timer enabled"
echo "Backup directory: $BACKUP_DIR"
echo "Backup retention: ${MARKET_BACKUP_RETENTION_DAYS:-14} days"
echo "Next backup: ${BACKUP_NEXT:-unknown}"
echo "Next health probe: ${HEALTH_NEXT:-unknown}"
echo "PASS: Market production operations enabled"
