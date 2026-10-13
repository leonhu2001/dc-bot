#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
BOT_SERVICE="${BOT_SERVICE:-dc-bot.service}"
WEB_SERVICE="${WEB_SERVICE:-dc-bot-dashboard.service}"
WEB_UNIT_PATH="${WEB_UNIT_PATH:-/etc/systemd/system/$WEB_SERVICE}"
NGINX_CONFIG_SOURCE="$APP/nginx_dc_bot_dashboard.conf"
NGINX_CONFIG_PATH="${NGINX_CONFIG_PATH:-}"
MARKER_PATH="$APP/data/deployed_version.json"
TARGET="${1:-}"
SERVICE_ACTIVE_ATTEMPTS="${DEPLOY_SERVICE_ACTIVE_ATTEMPTS:-20}"
SERVICE_ACTIVE_INTERVAL="${DEPLOY_SERVICE_ACTIVE_INTERVAL_SECONDS:-1}"
STABILITY_SAMPLES="${DEPLOY_STABILITY_SAMPLES:-5}"
STABILITY_INTERVAL="${DEPLOY_STABILITY_INTERVAL_SECONDS:-2}"

if [ -z "$TARGET" ]; then
    echo "Usage: $0 <target-commit>"
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: deployment must run as root."
    exit 2
fi

cd "$APP"

# If the install path is not explicitly configured, use an existing common path
# only. Never create a guessed Nginx site during a normal application deploy.
if [ -z "$NGINX_CONFIG_PATH" ]; then
    for candidate in \
        /etc/nginx/sites-available/dc-bot-dashboard \
        /etc/nginx/sites-available/dc-bot-dashboard.conf \
        /etc/nginx/conf.d/dc-bot-dashboard.conf; do
        if [ -e "$candidate" ]; then
            NGINX_CONFIG_PATH="$candidate"
            break
        fi
    done
fi

OLD_HEAD="$(git rev-parse HEAD)"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEPLOYED_AT="$(date --iso-8601=seconds)"
BACKUP="$APP/_archive/deploy_$STAMP"
SOURCE_UPDATED=0
DEPENDENCIES_UPDATED=0
DEPENDENCY_SYNC_NEEDED=0
WEB_UNIT_UPDATED=0
NGINX_CONFIG_UPDATED=0
SERVICES_RESTARTED=0
MARKER_EXISTED=0
MARKER_UPDATED=0

get_service_state() {
    local service="$1"
    local state

    state="$(systemctl is-active "$service" 2>/dev/null || true)"
    if [ -n "$state" ]; then
        printf '%s' "$state"
    else
        printf 'unknown'
    fi
}

get_service_restart_count() {
    local service="$1"
    local value

    value="$(systemctl show "$service" -p NRestarts --value 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
        printf '%s' "$value"
    else
        printf 'unknown'
    fi
}

print_service_diagnostics() {
    local service="$1"
    local label="$2"
    local state restarts

    state="$(get_service_state "$service")"
    restarts="$(get_service_restart_count "$service")"
    echo "$label state: $state"
    echo "$label NRestarts: $restarts"
    systemctl status "$service" --no-pager || true
    journalctl -u "$service" -n 100 --no-pager || true
}

wait_for_service_active() {
    local service="$1"
    local label="$2"
    local attempt state

    for attempt in $(seq 1 "$SERVICE_ACTIVE_ATTEMPTS"); do
        state="$(get_service_state "$service")"
        if [ "$state" = "active" ]; then
            echo "$label: active"
            return 0
        fi

        if [ "$attempt" -lt "$SERVICE_ACTIVE_ATTEMPTS" ]; then
            sleep "$SERVICE_ACTIVE_INTERVAL"
        fi
    done

    echo "ERROR: $label failed to become active after $SERVICE_ACTIVE_ATTEMPTS checks."
    print_service_diagnostics "$service" "$label"
    return 1
}

verify_service_stability() {
    local service="$1"
    local label="$2"
    local baseline_restarts current_restarts state sample

    baseline_restarts="$(get_service_restart_count "$service")"
    state="$(get_service_state "$service")"
    echo "$label stability baseline: state=$state NRestarts=$baseline_restarts"

    if [ "$state" != "active" ]; then
        echo "ERROR: $label is not active at the start of the stability window."
        print_service_diagnostics "$service" "$label"
        return 1
    fi

    for sample in $(seq 1 "$STABILITY_SAMPLES"); do
        sleep "$STABILITY_INTERVAL"
        state="$(get_service_state "$service")"
        current_restarts="$(get_service_restart_count "$service")"
        echo "$label stability $sample/$STABILITY_SAMPLES: state=$state NRestarts=$current_restarts"

        if [ "$state" != "active" ]; then
            echo "ERROR: $label left active state during deployment stabilization."
            print_service_diagnostics "$service" "$label"
            return 1
        fi

        if [[ "$baseline_restarts" =~ ^[0-9]+$ ]] \
            && [[ "$current_restarts" =~ ^[0-9]+$ ]] \
            && (( current_restarts > baseline_restarts )); then
            echo "ERROR: $label restarted during deployment stabilization ($baseline_restarts -> $current_restarts)."
            print_service_diagnostics "$service" "$label"
            return 1
        fi
    done

    return 0
}

write_deployment_marker() {
    local commit="$1"
    local previous_commit="$2"
    local deployed_at="$3"
    local subject="$4"
    local status="$5"
    local failed_target="${6:-}"

    mkdir -p "$APP/data"
    "$APP/venv/bin/python" - \
        "$MARKER_PATH" \
        "$commit" \
        "$previous_commit" \
        "$deployed_at" \
        "$subject" \
        "$status" \
        "$failed_target" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "commit": sys.argv[2],
    "previous_commit": sys.argv[3],
    "branch": "main",
    "deployed_at": sys.argv[4],
    "subject": sys.argv[5],
    "status": sys.argv[6],
}
if sys.argv[7]:
    payload["failed_target"] = sys.argv[7]
path.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
    chmod 0644 "$MARKER_PATH"
}

restart_services() {
    local started_at finished_at elapsed_ms
    started_at="$(date +%s%3N)"

    # 兩個 unit 放在同一個 systemd transaction，避免先等 Bot 完整重啟後
    # 才開始重啟 Web。HTTP readiness 交給後面的 smoke check，不再固定 sleep 3 秒。
    systemctl restart "$BOT_SERVICE" "$WEB_SERVICE"

    finished_at="$(date +%s%3N)"
    elapsed_ms=$((finished_at - started_at))
    echo "Restart transaction: ${elapsed_ms}ms"
}

rollback() {
    local rc=$?
    local rollback_subject rollback_at
    trap - ERR
    set +e

    echo
    echo "========================================"
    echo "  DEPLOY FAILED - ROLLBACK"
    echo "========================================"
    echo "Exit code: $rc"

    if [ "$SOURCE_UPDATED" -eq 1 ]; then
        echo "Rolling source back to: $OLD_HEAD"
        git reset --hard "$OLD_HEAD"
    fi

    if [ "$DEPENDENCIES_UPDATED" -eq 1 ] && [ -s "$BACKUP/venv-freeze.txt" ]; then
        echo "Restoring previous Python dependencies..."
        "$APP/venv/bin/python" -m pip install \
            --disable-pip-version-check \
            -r "$BACKUP/venv-freeze.txt" \
            || echo "WARN: dependency rollback failed; manual venv repair may be required."
    fi

    if [ "$WEB_UNIT_UPDATED" -eq 1 ] && [ -f "$BACKUP/$WEB_SERVICE" ]; then
        echo "Restoring previous web systemd unit..."
        install -m 0644 "$BACKUP/$WEB_SERVICE" "$WEB_UNIT_PATH"
        systemctl daemon-reload || true
    fi

    if [ "$NGINX_CONFIG_UPDATED" -eq 1 ] \
        && [ -n "$NGINX_CONFIG_PATH" ] \
        && [ -f "$BACKUP/nginx-dashboard.conf" ]; then
        echo "Restoring previous Nginx config..."
        install -m 0644 "$BACKUP/nginx-dashboard.conf" "$NGINX_CONFIG_PATH"
        nginx -t || true
        systemctl reload nginx || true
    fi

    if [ "$SERVICES_RESTARTED" -eq 1 ]; then
        restart_services || true

        echo "Bot after rollback: $(get_service_state "$BOT_SERVICE")"
        echo "Web after rollback: $(get_service_state "$WEB_SERVICE")"
    fi

    # A failed deployment must never leave a marker that claims the failed target
    # is live. Reconcile the marker to the source we actually rolled back to.
    if [ "$SOURCE_UPDATED" -eq 1 ]; then
        rollback_subject="$(git log -1 --format=%s "$OLD_HEAD" 2>/dev/null || echo rollback)"
        rollback_at="$(date --iso-8601=seconds 2>/dev/null || date)"
        if write_deployment_marker \
            "$OLD_HEAD" \
            "$TARGET" \
            "$rollback_at" \
            "$rollback_subject" \
            "rolled_back" \
            "$TARGET"; then
            echo "PASS: deployment marker reconciled to rollback source"
        elif [ "$MARKER_EXISTED" -eq 1 ] && [ -f "$BACKUP/deployed_version.json" ]; then
            echo "WARN: marker reconciliation failed; restoring previous marker backup"
            install -m 0644 "$BACKUP/deployed_version.json" "$MARKER_PATH" || true
        elif [ "$MARKER_UPDATED" -eq 1 ]; then
            rm -f "$MARKER_PATH" || true
        fi
    fi

    echo "Database backup retained at: $BACKUP"
    exit "$rc"
}

trap rollback ERR

echo "========================================"
echo "  SAFE MAIN DEPLOY"
echo "========================================"
echo
echo "App:      $APP"
echo "Old HEAD: $OLD_HEAD"
echo "Target:   $TARGET"
echo

echo "=== 1. PRECHECK ==="

DIRTY_WORKTREE="$(
    git status --porcelain --untracked-files=all \
        | grep -vE '^\?\? data/deployed_version\.json$' \
        || true
)"

if [ -n "$DIRTY_WORKTREE" ]; then
    echo "ERROR: VPS working tree is not clean."
    printf '%s\n' "$DIRTY_WORKTREE"
    exit 1
fi

mkdir -p "$BACKUP"

if [ -f "$MARKER_PATH" ]; then
    cp -L "$MARKER_PATH" "$BACKUP/deployed_version.json"
    MARKER_EXISTED=1
    echo "PASS: deployment marker backup"
fi

for db_name in bot.db web_dashboard.db; do
    if [ -e "$APP/$db_name" ]; then
        cp -L "$APP/$db_name" "$BACKUP/$db_name"
        echo "PASS: $db_name backup"
    else
        echo "WARN: $db_name not found"
    fi
done

if [ -f "$WEB_UNIT_PATH" ]; then
    cp -L "$WEB_UNIT_PATH" "$BACKUP/$WEB_SERVICE"
    echo "PASS: $WEB_SERVICE backup"
else
    echo "WARN: $WEB_UNIT_PATH not found"
fi

if [ -n "$NGINX_CONFIG_PATH" ] && [ -f "$NGINX_CONFIG_PATH" ]; then
    cp -L "$NGINX_CONFIG_PATH" "$BACKUP/nginx-dashboard.conf"
    echo "PASS: Nginx config backup ($NGINX_CONFIG_PATH)"
else
    echo "WARN: managed Nginx config path not detected; Nginx sync will be skipped"
fi

"$APP/venv/bin/python" -m pip freeze > "$BACKUP/venv-freeze.txt"
echo "PASS: Python dependency snapshot"

echo "Backup: $BACKUP"
echo

echo "=== 2. FETCH TARGET ==="
git fetch origin main

if ! git cat-file -e "${TARGET}^{commit}" 2>/dev/null; then
    echo "ERROR: target commit does not exist."
    exit 1
fi

ORIGIN_MAIN="$(git rev-parse origin/main)"

if ! git merge-base --is-ancestor "$TARGET" "$ORIGIN_MAIN"; then
    echo "ERROR: target is not contained in origin/main."
    echo "origin/main: $ORIGIN_MAIN"
    exit 1
fi

echo "origin/main: $ORIGIN_MAIN"

if ! git diff --quiet "$OLD_HEAD" "$TARGET" -- \
    requirements.txt \
    web/requirements-web.txt; then
    DEPENDENCY_SYNC_NEEDED=1
    echo "Dependency files changed: sync required"
else
    echo "Dependency files unchanged: sync skipped"
fi

echo

echo "=== 3. UPDATE SOURCE ==="
git checkout main
git reset --hard "$TARGET"
SOURCE_UPDATED=1

if [ "$(git rev-parse HEAD)" != "$TARGET" ]; then
    echo "ERROR: HEAD does not match target."
    false
fi

echo "PASS: source updated"
echo

echo "=== 4. SYNC PYTHON DEPENDENCIES ==="
if [ "$DEPENDENCY_SYNC_NEEDED" -eq 1 ]; then
    DEPENDENCIES_UPDATED=1

    "$APP/venv/bin/python" -m pip install \
        --disable-pip-version-check \
        --upgrade \
        -r requirements.txt \
        -r web/requirements-web.txt

    "$APP/venv/bin/python" -m pip check
    echo "PASS: Python dependencies synchronized"
else
    echo "SKIP: dependency files unchanged"
fi
echo

echo "=== 5. PYTHON COMPILE CHECK ==="
"$APP/venv/bin/python" -m compileall -q \
    bot.py \
    cogs \
    core \
    services \
    shared \
    views \
    web/app \
    tools \
    scripts

echo "PASS: Python compile"
echo

echo "=== 5B. RUNTIME IMPORT PREFLIGHT ==="
"$APP/venv/bin/python" "$APP/tools/runtime_import_smoke.py"
echo

echo "=== 6. ENSURE DATABASE TABLES ==="
runuser -u dc-bot-web -- env PYTHONPATH="$APP" \
    "$APP/venv/bin/python" -c "from shared.db import create_all_tables; create_all_tables(); print('PASS: database tables ready')"
echo

echo "=== 7. OPTIONAL VPS TESTS ==="
if "$APP/venv/bin/python" -c "import pytest" >/dev/null 2>&1; then
    "$APP/venv/bin/python" -m pytest -q --ignore=tests/e2e
else
    echo "SKIP: pytest is intentionally not required on production VPS."
fi

echo
echo "=== 7B. SYNC WEB SYSTEMD UNIT ==="
if cmp -s "$APP/dc-bot-dashboard.service" "$WEB_UNIT_PATH"; then
    echo "SKIP: web systemd unit unchanged"
else
    WEB_UNIT_UPDATED=1
    install -m 0644 "$APP/dc-bot-dashboard.service" "$WEB_UNIT_PATH"
    systemctl daemon-reload
    echo "PASS: web systemd unit synchronized"
fi

echo
echo "=== 7C. SYNC NGINX CONFIG ==="
if [ -z "$NGINX_CONFIG_PATH" ]; then
    echo "SKIP: managed Nginx config path not detected"
elif cmp -s "$NGINX_CONFIG_SOURCE" "$NGINX_CONFIG_PATH"; then
    echo "SKIP: Nginx config unchanged"
else
    NGINX_CONFIG_UPDATED=1
    install -m 0644 "$NGINX_CONFIG_SOURCE" "$NGINX_CONFIG_PATH"
    nginx -t
    systemctl reload nginx
    echo "PASS: Nginx config synchronized and reloaded"
fi

echo
echo "=== 8. RESTART SERVICES ==="
echo "Bot stop timeout: $(systemctl show "$BOT_SERVICE" -p TimeoutStopUSec --value 2>/dev/null || echo unknown)"
echo "Web stop timeout: $(systemctl show "$WEB_SERVICE" -p TimeoutStopUSec --value 2>/dev/null || echo unknown)"
SERVICES_RESTARTED=1
restart_services

if ! wait_for_service_active "$BOT_SERVICE" "Bot"; then
    false
fi

if ! wait_for_service_active "$WEB_SERVICE" "Web"; then
    false
fi

echo
echo "=== 9. HTTP SMOKE CHECK ==="
HEALTH_URL="${WEB_HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_RESPONSE=""
HEALTH_OK=0

for attempt in $(seq 1 15); do
    if HEALTH_RESPONSE="$(curl --fail --silent --max-time 3 "$HEALTH_URL" 2>/dev/null)"; then
        HEALTH_OK=1
        break
    fi

    if [ "$attempt" -lt 15 ]; then
        sleep 1
    fi
done

if [ "$HEALTH_OK" -ne 1 ]; then
    echo "ERROR: Web health endpoint did not become ready after 15 attempts."
    curl --fail --silent --show-error --max-time 3 "$HEALTH_URL" || true
    print_service_diagnostics "$WEB_SERVICE" "Web"
    false
fi

printf '%s\n' "$HEALTH_RESPONSE"
echo

echo "=== 10. FINAL STABILITY CHECK ==="
if ! FINAL_HEAD="$(git rev-parse HEAD)"; then
    echo "ERROR: failed to resolve final HEAD."
    false
fi

echo "HEAD: $FINAL_HEAD"
if [ "$FINAL_HEAD" != "$TARGET" ]; then
    echo "ERROR: final HEAD no longer matches deployment target."
    false
fi

if ! verify_service_stability "$BOT_SERVICE" "Bot"; then
    false
fi

if ! verify_service_stability "$WEB_SERVICE" "Web"; then
    false
fi

BOT_FINAL_STATE="$(get_service_state "$BOT_SERVICE")"
WEB_FINAL_STATE="$(get_service_state "$WEB_SERVICE")"
echo "Bot:  $BOT_FINAL_STATE"
echo "Web:  $WEB_FINAL_STATE"
if [ -n "$NGINX_CONFIG_PATH" ]; then
    NGINX_FINAL_STATE="$(get_service_state nginx)"
    echo "Nginx: $NGINX_FINAL_STATE"
fi
echo "Backup: $BACKUP"
echo

echo "=== 11. WRITE DEPLOYMENT MARKER ==="
SUBJECT="$(git log -1 --format=%s "$TARGET")"
MARKER_UPDATED=1
write_deployment_marker \
    "$TARGET" \
    "$OLD_HEAD" \
    "$DEPLOYED_AT" \
    "$SUBJECT" \
    "success"

echo "PASS: deployment marker written"
echo

# From this point onward there is no transactional work left. Disable rollback
# before printing success so a presentation-only failure can never rewrite source.
trap - ERR

echo "========================================"
echo "  SAFE DEPLOY SUCCESS"
echo "========================================"
