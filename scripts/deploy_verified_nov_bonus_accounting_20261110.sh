#!/usr/bin/env bash
# Isolated website-only deployment of the verified Nov 2% reconciliation fix.
set -Eeuo pipefail

APP=/opt/dc-bot
RELEASE_REF=fix/verified-nov-bonus-accounting-alerts-20261110
REQUIRED_BASE=4386dddf1da66adb01d55a5ffdf4df42749912e2
PRICE_BASE=d637f16412d15bb8bc77229d105c7816b35da06d
TARGET="${1:-}"
WEB_SERVICE=dc-bot-dashboard.service

if [[ -z "$TARGET" ]]; then
    echo "Usage: bash deploy_verified_nov_bonus_accounting_20261110.sh TARGET"
    exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: must run as root."
    exit 2
fi

cd "$APP"
OLD_HEAD="$(git rev-parse HEAD)"
if [[ "$OLD_HEAD" != "$REQUIRED_BASE" ]]; then
    echo "BLOCKED: VPS HEAD $OLD_HEAD differs from approved base $REQUIRED_BASE."
    echo "No services or files changed."
    exit 2
fi

DIRTY="$(
    git status --porcelain --untracked-files=all |
        grep -vE '^\?\? (data/(deployed_version|market_poll_state)\.json|web/app/static/images/payment/(cathay_qr|jkopay_qr)\.jpg)$' ||
        true
)"
if [[ -n "$DIRTY" ]]; then
    echo "BLOCKED: VPS worktree not clean:"
    printf '%s\n' "$DIRTY"
    exit 2
fi

git fetch origin "+refs/heads/$RELEASE_REF:refs/remotes/origin/$RELEASE_REF"
if [[ "$(git rev-parse "origin/$RELEASE_REF")" != "$TARGET" ]]; then
    echo "BLOCKED: target differs from isolated release branch."
    exit 2
fi

echo "=== VERIFY TARGET CI ==="
RUNS_JSON="$(curl --fail --silent --show-error --max-time 15 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: dc-bot-safe-accounting-deploy' \
    "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$TARGET&per_page=20")"
printf '%s' "$RUNS_JSON" | ./venv/bin/python -c '
import json,sys
target=sys.argv[1]; branch=sys.argv[2]
runs=json.load(sys.stdin).get("workflow_runs",[])
matches=[r for r in runs if r.get("name")=="CI"
         and r.get("head_branch")==branch
         and r.get("head_sha")==target
         and r.get("event")=="push"]
if not matches or matches[0].get("status")!="completed" or matches[0].get("conclusion")!="success":
    sys.exit("BLOCKED: exact isolated-branch CI not successful")
print("PASS: CI successful")
' "$TARGET" "$RELEASE_REF"

echo "=== VERIFY FILE SCOPE & PRICES ==="
while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    case "$path" in
        .github/workflows/ci.yml|\
        web/app/services/accounting_reconciliation_policy.py|\
        tests/test_verified_nov_bonus_accounting_alerts_20261110.py|\
        scripts/deploy_verified_nov_bonus_accounting_20261110.sh)
            ;;
        *)
            echo "BLOCKED: unexpected changed file: $path"
            exit 2
            ;;
    esac
done < <(git diff --name-only "$OLD_HEAD" "$TARGET")

if ! git diff --quiet "$PRICE_BASE" "$TARGET" -- \
    services/order_rules.py \
    services/quick_order_v2_price_lists.py \
    services/one_companion_one_guard_catalog.py \
    services/one_companion_one_guard_payout.py \
    services/orders.py \
    services/vip_timer_roster_payout.py \
    services/self_service_point_benefit_policy.py \
    web/app/services/order_groups.py \
    web/app/services/order_service.py \
    web/app/services/checkout_preview.py; then
    echo "BLOCKED: Delta price/calculation source changed"
    exit 2
fi
echo "PASS: only accounting policy, test, CI and deploy scripts changed"
echo "PASS: Delta prices unchanged"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/accounting_nov_bonus_$STAMP"
mkdir -p "$BACKUP"
MARKER="$APP/data/deployed_version.json"
if [[ -f "$MARKER" ]]; then
    cp -L "$MARKER" "$BACKUP/deployed_version.json"
fi
APPLIED=0
rollback() {
    local rc=$?
    trap - ERR
    if [[ "$APPLIED" -eq 1 ]]; then
        echo "DEPLOY FAILED: restoring $OLD_HEAD"
        git reset --hard "$OLD_HEAD" || true
        systemctl restart "$WEB_SERVICE" || true
        if [[ -f "$BACKUP/deployed_version.json" ]]; then
            cp -L "$BACKUP/deployed_version.json" "$MARKER" || true
        fi
    fi
    exit "$rc"
}
trap rollback ERR

echo "=== UPDATE WEBSITE CODE (NO DATABASE WRITES) ==="
git checkout -B "$RELEASE_REF" "$TARGET"
APPLIED=1
./venv/bin/python -m py_compile web/app/services/accounting_reconciliation_policy.py

echo "=== VERIFY TWO APPROVED BONUS LEDGERS READ ONLY ==="
./venv/bin/python - <<'PY'
from pathlib import Path
from web.app.services.accounting_reconciliation_policy import (
    _connect_readonly, _is_verified_nov_bonus_repair,
    _policy_consistency_for_order,
)
db = _connect_readonly(Path("web_dashboard.db"))
if db is None:
    raise SystemExit("BLOCKED: live DB not readable")
try:
    for oid in (298, 300):
        proof = _is_verified_nov_bonus_repair(db, oid)
        state = _policy_consistency_for_order(db, oid)
        print(f"ORDER #{oid}: audit={proof}, state={state}")
        if not proof or not state["worker_consistent"] or not state["cs_consistent"]:
            raise SystemExit(f"BLOCKED: #{oid} requires manual accounting review; no financial data changed")
finally:
    db.close()
PY

echo "=== RESTART WEBSITE ONLY ==="
systemctl restart "$WEB_SERVICE"
systemctl is-active --quiet "$WEB_SERVICE"
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8000/health
echo
./venv/bin/python - <<'PY'
from pathlib import Path
from web.app.services.accounting_reconciliation_policy import build_accounting_policy_view
snapshot, suppressed = build_accounting_policy_view(Path("."))
for oid in (298, 300):
    found = {item["code"] for item in suppressed if item.get("order_id") == oid}
    print(f"ORDER #{oid}: suppressed legacy amount-only alerts = {sorted(found)}")
    if found != {
        "worker_payout_amount_mismatch",
        "customer_service_payout_amount_mismatch",
    }:
        raise SystemExit(f"BLOCKED: #{oid} did not suppress both verified false positives")
print(f"PASS: verified all four false positives removed; remaining anomalies={snapshot['issue_count']}")
PY
./venv/bin/python - "$MARKER" "$TARGET" "$OLD_HEAD" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path=Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps({
    "commit":sys.argv[2], "previous_commit":sys.argv[3],
    "branch":"fix/verified-nov-bonus-accounting-alerts-20261110",
    "deployed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "subject":"Verified November bonus reconciliation UI-only fix",
    "status":"success",
},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
APPLIED=0
trap - ERR
echo "DEPLOY COMPLETED - WEB ONLY, NO DB CHANGES"
echo "Commit: $TARGET"
