#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
WEB_ENV="$APP/web/.env"
BOT_ENV="$APP/data/market_discord.env"
BOT_SERVICE="${BOT_SERVICE:-dc-bot.service}"
TARGET_CHANNEL="1566004926209990776"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$APP/_archive/market_discord_setup_$STAMP"
TMP_ENV=""
BOT_ENV_EXISTED=0
SETUP_COMPLETE=0
CREDENTIAL_INSTALLED=0

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Discord market production setup must run as root."
    exit 2
fi

cd "$APP"

for path in "$WEB_ENV" "$APP/venv/bin/python" "$APP/services/market/discord_runtime.py"; do
    if [ ! -e "$path" ]; then
        echo "ERROR: missing $path"
        exit 2
    fi
done

if ! systemctl cat "$BOT_SERVICE" >/dev/null 2>&1; then
    echo "ERROR: $BOT_SERVICE is not installed."
    exit 2
fi

BOT_USER="$(systemctl show "$BOT_SERVICE" -p User --value)"
if [ -z "$BOT_USER" ]; then
    BOT_USER="root"
fi
if ! id "$BOT_USER" >/dev/null 2>&1; then
    echo "ERROR: bot service user does not exist."
    exit 2
fi

BOT_GROUP="$(systemctl show "$BOT_SERVICE" -p Group --value)"
if [ -z "$BOT_GROUP" ]; then
    BOT_GROUP="$(id -gn "$BOT_USER")"
fi

mkdir -p "$BACKUP_DIR" "$APP/data"
chmod 0700 "$BACKUP_DIR"
if [ -f "$BOT_ENV" ]; then
    cp -a "$BOT_ENV" "$BACKUP_DIR/market_discord.env"
    BOT_ENV_EXISTED=1
fi

cleanup_temp() {
    if [ -n "$TMP_ENV" ] && [ -e "$TMP_ENV" ]; then
        rm -f "$TMP_ENV"
    fi
}

rollback() {
    local rc=$?
    trap - ERR
    set +e
    cleanup_temp

    if [ "$SETUP_COMPLETE" -eq 1 ]; then
        exit "$rc"
    fi

    if [ "$CREDENTIAL_INSTALLED" -eq 1 ]; then
        if [ "$BOT_ENV_EXISTED" -eq 1 ] && [ -f "$BACKUP_DIR/market_discord.env" ]; then
            cp -a "$BACKUP_DIR/market_discord.env" "$BOT_ENV"
            echo "PASS: previous Discord Market credential restored"
        else
            rm -f "$BOT_ENV"
            echo "PASS: new Discord Market credential removed"
        fi
        systemctl restart "$BOT_SERVICE" >/dev/null 2>&1 || true
    fi

    echo "DISCORD MARKET SETUP FAILED"
    echo "Backup retained at: $BACKUP_DIR"
    exit "$rc"
}
trap rollback ERR
trap cleanup_temp EXIT

TMP_ENV="$(mktemp)"
"$APP/venv/bin/python" - "$WEB_ENV" "$TMP_ENV" <<'PY'
import sys
from pathlib import Path
from dotenv import dotenv_values

source = Path(sys.argv[1])
target = Path(sys.argv[2])
value = str(dotenv_values(source).get("MARKET_DATABASE_URL") or "").strip()
if not value:
    raise SystemExit("MARKET_DATABASE_URL is missing from web/.env")
if not value.startswith("postgresql"):
    raise SystemExit("MARKET_DATABASE_URL must be PostgreSQL in production")
target.write_text(f"MARKET_DATABASE_URL={value}\n", encoding="utf-8")
PY

install -o "$BOT_USER" -g "$BOT_GROUP" -m 0600 "$TMP_ENV" "$BOT_ENV"
CREDENTIAL_INSTALLED=1
rm -f "$TMP_ENV"
TMP_ENV=""
echo "PASS: dedicated Discord Market credential installed"

runuser -u "$BOT_USER" -- env \
    PYTHONPATH="$APP" \
    APP_DIR="$APP" \
    MARKET_DISCORD_ENV_FILE="$BOT_ENV" \
    "$APP/venv/bin/python" - <<'PY'
from services.market.discord_runtime import get_discord_market_services

services = get_discord_market_services()
if services is None:
    raise SystemExit("Discord Market runtime did not load")
latest = services.market.list_latest("delta_force", limit=500)
if not latest:
    raise SystemExit("Discord Market runtime cannot read latest prices")
print(f"PASS: Discord Market DB preflight items={len(latest)}")
PY

# journalctl accepts its native local-time timestamp format more consistently than
# ISO 8601 offsets across distro/systemd versions.
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
systemctl restart "$BOT_SERVICE"

ready=0
for _ in $(seq 1 30); do
    if [ "$(systemctl is-active "$BOT_SERVICE" 2>/dev/null || true)" = "active" ]; then
        ready=1
        break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    systemctl status "$BOT_SERVICE" --no-pager || true
    journalctl -u "$BOT_SERVICE" -n 120 --no-pager || true
    echo "ERROR: $BOT_SERVICE did not become active."
    false
fi

echo "Waiting for Discord panel synchronization..."
panel_ready=0
# The production bot performs substantial on_ready restoration work and may hit
# Discord's normal HTTP rate limits while refreshing existing panels. Market setup
# must wait for the actual sync marker instead of assuming startup finishes in 30s.
for _ in $(seq 1 180); do
    if [ "$(systemctl is-active "$BOT_SERVICE" 2>/dev/null || true)" != "active" ]; then
        systemctl status "$BOT_SERVICE" --no-pager || true
        journalctl -u "$BOT_SERVICE" --since "$STARTED_AT" -n 160 --no-pager || true
        echo "ERROR: $BOT_SERVICE stopped while waiting for Discord Market panels."
        false
    fi

    if journalctl -u "$BOT_SERVICE" --since "$STARTED_AT" --no-pager 2>/dev/null \
        | grep -Fq "[market-discord] panels synced channel=$TARGET_CHANNEL"; then
        panel_ready=1
        break
    fi
    sleep 1
done

if [ "$panel_ready" -ne 1 ]; then
    journalctl -u "$BOT_SERVICE" --since "$STARTED_AT" -n 200 --no-pager || true
    echo "ERROR: Discord Market panels were not confirmed in target channel $TARGET_CHANNEL."
    false
fi

echo "PASS: Discord Market panels synced to channel $TARGET_CHANNEL"
echo "PASS: Discord Market DM runtime enabled"
echo "Backup retained at: $BACKUP_DIR"
SETUP_COMPLETE=1
trap - ERR
