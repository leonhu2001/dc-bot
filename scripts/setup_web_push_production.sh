#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
ENV_FILE="$APP/web/.env"
WEB_SERVICE="${WEB_SERVICE:-dc-bot-dashboard.service}"
MARKET_SERVICE="${MARKET_SERVICE:-dc-bot-market.service}"
DEFAULT_SUBJECT="${WEB_PUSH_VAPID_SUBJECT_DEFAULT:-mailto:admin@mowanentertainment.com}"
BACKUP_DIR="$APP/_archive/web_push_setup_$(date +%Y%m%d_%H%M%S)"
ENV_UPDATED=0

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: web push production setup must run as root."
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

mkdir -p "$BACKUP_DIR"
cp -a "$ENV_FILE" "$BACKUP_DIR/web.env"
echo "Backup: $BACKUP_DIR/web.env"

restart_runtime_services() {
    local services=("$WEB_SERVICE")
    if systemctl cat "$MARKET_SERVICE" >/dev/null 2>&1; then
        services+=("$MARKET_SERVICE")
    fi
    systemctl restart "${services[@]}"
}

rollback() {
    local rc=$?
    trap - ERR
    set +e
    echo
    echo "WEB PUSH SETUP FAILED - restoring previous environment"
    if [ "$ENV_UPDATED" -eq 1 ] && [ -f "$BACKUP_DIR/web.env" ]; then
        cp -a "$BACKUP_DIR/web.env" "$ENV_FILE"
        restart_runtime_services || true
        echo "PASS: previous web/.env restored"
    fi
    echo "Backup retained at: $BACKUP_DIR"
    exit "$rc"
}
trap rollback ERR

# Generate and validate the VAPID pair entirely on the VPS. The private key is
# written directly to web/.env and is never printed to stdout or sent to GitHub.
"$APP/venv/bin/python" - "$ENV_FILE" "$DEFAULT_SUBJECT" <<'PY'
import base64
import sys
from pathlib import Path

from dotenv import dotenv_values
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

path = Path(sys.argv[1])
default_subject = sys.argv[2].strip()
values = dotenv_values(path)
public = str(values.get("WEB_PUSH_VAPID_PUBLIC_KEY") or "").strip()
private = str(values.get("WEB_PUSH_VAPID_PRIVATE_KEY") or "").strip()
subject = str(values.get("WEB_PUSH_VAPID_SUBJECT") or "").strip() or default_subject

if not (subject.startswith("mailto:") or subject.startswith("https://")):
    raise SystemExit("WEB_PUSH_VAPID_SUBJECT must start with mailto: or https://")
if bool(public) != bool(private):
    raise SystemExit("existing VAPID configuration is incomplete; refusing to rotate only one key")

def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def derived_public(vapid: Vapid) -> str:
    return b64url(
        vapid.public_key.public_bytes(
            encoding=Encoding.X962,
            format=PublicFormat.UncompressedPoint,
        )
    )

created = False
if public and private:
    vapid = Vapid.from_string(private)
    if derived_public(vapid) != public:
        raise SystemExit("existing VAPID public/private keys do not match; refusing automatic rotation")
else:
    vapid = Vapid()
    vapid.generate_keys()
    private_value = vapid.private_key.private_numbers().private_value
    private = b64url(private_value.to_bytes(32, "big"))
    public = derived_public(vapid)
    created = True

updates = {
    "WEB_PUSH_VAPID_PUBLIC_KEY": public,
    "WEB_PUSH_VAPID_PRIVATE_KEY": private,
    "WEB_PUSH_VAPID_SUBJECT": subject,
}
raw = path.read_text(encoding="utf-8")
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
print("PASS: VAPID key pair generated" if created else "KEEP: existing VAPID key pair validated")
print("PASS: VAPID subject configured")
PY
ENV_UPDATED=1

# Validate using the same configuration reader used by the web and worker code.
runuser -u dc-bot-web -- env PYTHONPATH="$APP" APP_DIR="$APP" \
    "$APP/venv/bin/python" - "$ENV_FILE" <<'PY'
import base64
import sys
from dotenv import load_dotenv
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

load_dotenv(sys.argv[1], override=True)
from services.market.push_dispatcher import get_web_push_config

config = get_web_push_config()
if not config.enabled:
    raise SystemExit("web push config is not enabled after setup")
vapid = Vapid.from_string(config.private_key)
derived = base64.urlsafe_b64encode(
    vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
).decode("ascii").rstrip("=")
if derived != config.public_key:
    raise SystemExit("VAPID key validation failed after setup")
print("PASS: application Web Push configuration enabled and key pair verified")
PY

restart_runtime_services

for service in "$WEB_SERVICE"; do
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
        exit 1
    fi
done

if systemctl cat "$MARKET_SERVICE" >/dev/null 2>&1; then
    ready=0
    for _ in $(seq 1 20); do
        if [ "$(systemctl is-active "$MARKET_SERVICE" 2>/dev/null || true)" = "active" ]; then
            ready=1
            break
        fi
        sleep 1
    done
    if [ "$ready" -ne 1 ]; then
        echo "ERROR: $MARKET_SERVICE did not become active."
        systemctl status "$MARKET_SERVICE" --no-pager || true
        journalctl -u "$MARKET_SERVICE" -n 100 --no-pager || true
        exit 1
    fi
fi

HEALTH=""
for _ in $(seq 1 15); do
    if HEALTH="$(curl --fail --silent --max-time 3 http://127.0.0.1:8000/health 2>/dev/null)"; then
        break
    fi
    sleep 1
done
if [ -z "$HEALTH" ]; then
    echo "ERROR: web health check failed after Web Push activation."
    exit 1
fi

echo "$HEALTH"
# Market health is informative here: source staleness must not roll back a valid
# VAPID setup. Print it even when the dedicated endpoint returns HTTP 503.
curl --silent --show-error --max-time 5 http://127.0.0.1:8000/health/market || true
echo

echo "PASS: production Web Push enabled"
echo "Backup retained at: $BACKUP_DIR"
trap - ERR
