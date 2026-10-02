#!/usr/bin/env bash
set -Eeuo pipefail

APP="${APP_DIR:-/opt/dc-bot}"
BOT_SERVICE="${BOT_SERVICE:-dc-bot.service}"
WEB_SERVICE="${WEB_SERVICE:-dc-bot-dashboard.service}"
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
    echo "Usage: $0 <target-commit>"
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: deployment must run as root."
    exit 2
fi

cd "$APP"

OLD_HEAD="$(git rev-parse HEAD)"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEPLOYED_AT="$(date --iso-8601=seconds)"
BACKUP="$APP/_archive/deploy_$STAMP"
SOURCE_UPDATED=0
DEPENDENCIES_UPDATED=0
DEPENDENCY_SYNC_NEEDED=0

rollback() {
    local rc=$?
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

    if [ "$SOURCE_UPDATED" -eq 1 ]; then
        systemctl restart "$BOT_SERVICE"
        systemctl restart "$WEB_SERVICE"
        sleep 3

        echo "Bot after rollback: $(systemctl is-active "$BOT_SERVICE" || true)"
        echo "Web after rollback: $(systemctl is-active "$WEB_SERVICE" || true)"
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

if [ -e "$APP/data/deployed_version.json" ]; then
    echo "PASS: ignored runtime marker data/deployed_version.json"
fi

mkdir -p "$BACKUP"

for db_name in bot.db web_dashboard.db; do
    if [ -e "$APP/$db_name" ]; then
        cp -L "$APP/$db_name" "$BACKUP/$db_name"
        echo "PASS: $db_name backup"
    else
        echo "WARN: $db_name not found"
    fi
done

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
    exit 1
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
/opt/dc-bot/venv/bin/python -m compileall -q \
    bot.py \
    cogs \
    core \
    services \
    shared \
    web/app

echo "PASS: Python compile"
echo

echo "=== 6. ENSURE DATABASE TABLES ==="
runuser -u dc-bot-web -- env PYTHONPATH="$APP" \
    "$APP/venv/bin/python" -c "from shared.db import create_all_tables; create_all_tables(); print('PASS: database tables ready')"
echo

echo "=== 7. OPTIONAL VPS TESTS ==="
if /opt/dc-bot/venv/bin/python -c "import pytest" >/dev/null 2>&1; then
    /opt/dc-bot/venv/bin/python -m pytest -q
else
    echo "SKIP: pytest is intentionally not required on production VPS."
fi

echo
echo "=== 8. RESTART SERVICES ==="
systemctl restart "$BOT_SERVICE"
systemctl restart "$WEB_SERVICE"
sleep 3

BOT_STATE="$(systemctl is-active "$BOT_SERVICE" || true)"
WEB_STATE="$(systemctl is-active "$WEB_SERVICE" || true)"

echo "Bot: $BOT_STATE"
echo "Web: $WEB_STATE"

if [ "$BOT_STATE" != "active" ]; then
    echo "ERROR: Bot failed to become active."
    journalctl -u "$BOT_SERVICE" -n 80 --no-pager || true
    false
fi

if [ "$WEB_STATE" != "active" ]; then
    echo "ERROR: Web failed to become active."
    journalctl -u "$WEB_SERVICE" -n 80 --no-pager || true
    false
fi

echo
echo "=== 9. HTTP SMOKE CHECK ==="
curl --fail --silent --show-error \
    --retry 5 \
    --retry-delay 1 \
    --retry-connrefused \
    http://127.0.0.1:8000/health

echo
echo

echo "=== 10. WRITE DEPLOYMENT MARKER ==="
SUBJECT="$(git log -1 --format=%s "$TARGET")"
mkdir -p "$APP/data"

/opt/dc-bot/venv/bin/python - \
    "$APP/data/deployed_version.json" \
    "$TARGET" \
    "$OLD_HEAD" \
    "$DEPLOYED_AT" \
    "$SUBJECT" <<'PY'
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
    "status": "success",
}
path.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

chmod 0644 "$APP/data/deployed_version.json"

echo "PASS: deployment marker written"
echo

echo "=== 11. FINAL CHECK ==="
echo "HEAD: $(git rev-parse HEAD)"
echo "Bot:  $(systemctl is-active "$BOT_SERVICE")"
echo "Web:  $(systemctl is-active "$WEB_SERVICE")"
echo "Backup: $BACKUP"

echo
echo "========================================"
echo "  SAFE DEPLOY SUCCESS"
echo "========================================"
