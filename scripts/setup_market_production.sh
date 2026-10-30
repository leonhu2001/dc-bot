#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
ENV_FILE="$APP/web/.env"
MARKET_SERVICE="${MARKET_SERVICE:-dc-bot-market.service}"
MARKET_UNIT_PATH="${MARKET_UNIT_PATH:-/etc/systemd/system/$MARKET_SERVICE}"
WEB_SERVICE="${WEB_SERVICE:-dc-bot-dashboard.service}"
BACKUP_DIR="$APP/_archive/market_setup_$(date +%Y%m%d_%H%M%S)"
DB_ROLE="${MARKET_DB_ROLE:-mowan_market}"
DB_NAME="${MARKET_DB_NAME:-mowan_market}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: market production setup must run as root."
    exit 2
fi

cd "$APP"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE does not exist."
    exit 2
fi
if [ ! -x "$APP/venv/bin/python" ]; then
    echo "ERROR: $APP/venv/bin/python does not exist."
    exit 2
fi
if [ ! -f "$APP/dc-bot-market.service" ]; then
    echo "ERROR: dc-bot-market.service is missing from the deployed source."
    exit 2
fi

mkdir -p "$BACKUP_DIR"
cp -L "$ENV_FILE" "$BACKUP_DIR/web.env"
echo "Backup: $BACKUP_DIR/web.env"

CURRENT_MARKET_DATABASE_URL="$(
    "$APP/venv/bin/python" - "$ENV_FILE" <<'PY'
import sys
from dotenv import dotenv_values
value = dotenv_values(sys.argv[1]).get("MARKET_DATABASE_URL") or ""
print(str(value).strip())
PY
)"

if [ -z "$CURRENT_MARKET_DATABASE_URL" ]; then
    if ! command -v psql >/dev/null 2>&1 || ! id postgres >/dev/null 2>&1; then
        if ! command -v apt-get >/dev/null 2>&1; then
            echo "ERROR: PostgreSQL is not installed and apt-get is unavailable."
            exit 2
        fi
        echo "Installing PostgreSQL..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y postgresql
    fi

    systemctl enable --now postgresql

    DB_PASSWORD="$("$APP/venv/bin/python" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"

    if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_ROLE'" | grep -qx '1'; then
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE $DB_ROLE WITH LOGIN PASSWORD '$DB_PASSWORD';" >/dev/null
    else
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE $DB_ROLE LOGIN PASSWORD '$DB_PASSWORD';" >/dev/null
    fi

    if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -qx '1'; then
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE $DB_NAME OWNER TO $DB_ROLE;" >/dev/null
    else
        runuser -u postgres -- createdb --owner="$DB_ROLE" "$DB_NAME"
    fi

    CURRENT_MARKET_DATABASE_URL="postgresql+psycopg2://$DB_ROLE:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME"
    echo "PASS: dedicated PostgreSQL market database provisioned"
else
    echo "KEEP: existing MARKET_DATABASE_URL is already configured"
fi

"$APP/venv/bin/python" - "$ENV_FILE" "$CURRENT_MARKET_DATABASE_URL" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
database_url = sys.argv[2]
updates = {
    "MARKET_DATABASE_URL": database_url,
    "MARKET_PROVIDER": "852941-tw",
    "MARKET_852941_BASE_URL": "https://app.852941.xyz",
    "MARKET_GAME_KEYS": "delta_force",
    "MARKET_POLL_SECONDS": "900",
    "MARKET_STALE_SECONDS": "2700",
}

raw = path.read_text(encoding="utf-8") if path.exists() else ""
lines = raw.splitlines()
seen = set()
out = []
for line in lines:
    stripped = line.lstrip()
    replaced = False
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            if key not in seen:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
            replaced = True
    if not replaced:
        out.append(line)

if out and out[-1].strip():
    out.append("")
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

echo "PASS: market environment configured (database credential hidden)"

install -m 0644 "$APP/dc-bot-market.service" "$MARKET_UNIT_PATH"
systemctl daemon-reload
systemctl enable "$MARKET_SERVICE" >/dev/null

echo "Running market DB/provider preflight and first ingest..."
runuser -u dc-bot-web -- env PYTHONPATH="$APP" \
    "$APP/venv/bin/python" - "$APP" <<'PY'
import asyncio
import os
import sys
from dotenv import load_dotenv

app = sys.argv[1]
load_dotenv(f"{app}/web/.env", override=True)

from services.market.personalization import MarketPersonalizationRepository
from services.market.provider_registry import build_configured_provider
from services.market.push import MarketPushRepository
from services.market.storage import MarketRepository
from services.market.worker import run_market_cycle

url = (os.getenv("MARKET_DATABASE_URL") or "").strip()
if not url:
    raise SystemExit("MARKET_DATABASE_URL is empty after setup")
provider = build_configured_provider()
if provider is None:
    raise SystemExit("MARKET_PROVIDER did not build")

repo = MarketRepository(url)
repo.create_all()
personalization = MarketPersonalizationRepository(repo)
personalization.create_all()
push = MarketPushRepository(repo)
push.create_all()

results = asyncio.run(
    run_market_cycle(
        provider=provider,
        repository=repo,
        personalization=personalization,
        game_keys=("delta_force",),
    )
)
result = results[0]
if result.status not in {"stored", "duplicate"}:
    raise SystemExit(f"first market ingest failed: {result.status}: {result.message}")
latest = repo.list_latest("delta_force", limit=500)
if not latest:
    raise SystemExit("market DB contains no latest items after ingest")
print(
    "PASS: first market ingest",
    f"status={result.status}",
    f"inserted={result.inserted_price_count}",
    f"items={len(latest)}",
    f"source={result.message}",
)
PY

# Restart the web process so it loads MARKET_DATABASE_URL, and start/restart the
# worker in the same transaction. PartOf keeps future normal web deploy restarts
# synchronized with the already-enabled market worker.
systemctl restart "$WEB_SERVICE" "$MARKET_SERVICE"

for service in "$WEB_SERVICE" "$MARKET_SERVICE"; do
    ready=0
    for _ in $(seq 1 20); do
        if [ "$(systemctl is-active "$service" 2>/dev/null || true)" = "active" ]; then
            ready=1
            break
        fi
        sleep 1
    done
    if [ "$ready" -ne 1 ]; then
        echo "ERROR: $service did not become active."
        systemctl status "$service" --no-pager || true
        journalctl -u "$service" -n 100 --no-pager || true
        exit 1
    fi
done

HEALTH=""
for _ in $(seq 1 15); do
    if HEALTH="$(curl --fail --silent --max-time 3 http://127.0.0.1:8000/health 2>/dev/null)"; then
        break
    fi
    sleep 1
done
if [ -z "$HEALTH" ]; then
    echo "ERROR: web health check failed after market activation."
    exit 1
fi

MARKET_STATE="$(systemctl is-active "$MARKET_SERVICE")"
MARKET_ENABLED="$(systemctl is-enabled "$MARKET_SERVICE")"
echo "$HEALTH"
echo "Market worker: $MARKET_STATE / $MARKET_ENABLED"
echo "PASS: production market pipeline enabled"
echo "Backup retained at: $BACKUP_DIR"
