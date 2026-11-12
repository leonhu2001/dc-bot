#!/usr/bin/env bash
# Deploy public/internal farm priority and ticket idempotency atomically.
# Production database rows and already-paid salary ledgers are never rewritten.
set -Eeuo pipefail

APP=/opt/dc-bot
BOT_SERVICE=dc-bot.service
WEB_SERVICE=dc-bot-dashboard.service
RELEASE_REF=feat/farm-priority-worker-only-and-ticket-idempotency-20261112
OLD_FARM_RELEASE=ed70f897a1dc4178922df8296cb6d1395acf61f5
OLD_PANEL_RELEASE=b179aa72b50400ccf01d80840e145dbdb2e6accc
OLD_EXAMINER_RELEASE=a34a2fb0046568b66a7a295132c2444f63e338d7
TARGET="${1:-}"

if [[ -z "$TARGET" || "$(id -u)" -ne 0 ]]; then
    echo "Usage: root bash deploy_priority_farm_ticket_20261112.sh COMMIT_SHA"
    exit 2
fi
cd "$APP"
OLD_HEAD="$(git rev-parse HEAD)"
case "$OLD_HEAD" in
    "$OLD_FARM_RELEASE"|"$OLD_PANEL_RELEASE"|"$OLD_EXAMINER_RELEASE") ;;
    *) echo "BLOCKED: VPS is on an unexpected release: $OLD_HEAD"; exit 2 ;;
esac

DIRTY="$(git status --porcelain --untracked-files=all |
    grep -vE '^\?\? (data/(deployed_version|market_poll_state)\.json|web/app/static/images/payment/(cathay_qr|jkopay_qr)\.jpg)$' || true)"
if [[ -n "$DIRTY" ]]; then
    echo "BLOCKED: VPS has unexpected local edits"
    printf '%s\n' "$DIRTY"
    exit 2
fi

echo "=== PINNED RELEASE & GITHUB CI ==="
git fetch origin "+refs/heads/$RELEASE_REF:refs/remotes/origin/$RELEASE_REF"
if [[ "$(git rev-parse "origin/$RELEASE_REF")" != "$TARGET" ]]; then
    echo "BLOCKED: commit does not match the owner-approved release branch HEAD"
    exit 2
fi
RUNS="$(curl --fail --silent --show-error --max-time 20 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: mw-priority-farm-safe-release' \
    "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$TARGET&per_page=20")"
printf '%s' "$RUNS" | ./venv/bin/python -c '
import json,sys
target,branch=sys.argv[1:3]
runs=json.load(sys.stdin).get("workflow_runs",[])
valid=[r for r in runs if r.get("name")=="CI" and r.get("event")=="push"
       and r.get("head_sha")==target and r.get("head_branch")==branch
       and r.get("status")=="completed" and r.get("conclusion")=="success"]
if not valid:
    raise SystemExit("BLOCKED: exact priority release CI has not passed")
print("PASS: pinned successful CI on exact SHA")
' "$TARGET" "$RELEASE_REF"

echo "=== STRICT SCOPE GUARD ==="
while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    case "$path" in
        .github/workflows/ci.yml|\
        bot.py|\
        views/panels.py|\
        services/farm_fixed_cut_policy.py|\
        services/staff_internal_ammo_dump_policy.py|\
        services/staff_internal_ammo_dump_ui.py|\
        services/order_rules.py|\
        services/orders.py|\
        services/one_companion_one_guard_payout.py|\
        services/self_service_financials.py|\
        services/self_service_financial_breakdown_display.py|\
        services/self_service_ui_runtime.py|\
        services/quick_order_v2.py|\
        services/quick_order_v2_price_lists.py|\
        services/quick_order_ticket_dedupe_policy.py|\
        web/app/services/order_groups.py|\
        web/app/services/checkout_preview.py|\
        web/app/services/order_service.py|\
        web/app/services/worker_bonus_payout.py|\
        scripts/deploy_support_panel_links_20261111.sh|\
        scripts/deploy_support_panel_links_20261111.ps1|\
        scripts/deploy_priority_farm_ticket_20261112.sh|\
        scripts/deploy_priority_farm_ticket_20261112.ps1|\
        tests/test_farm_priority_ticket_dedupe_20261112.py|\
        tests/test_public_farm_fixed_cut_20261111.py|\
        tests/test_staff_internal_delta_orders_20261105.py|\
        tests/test_internal_ammo_named_pricing_20261105.py|\
        tests/test_coin_wash_aw_exclusive_receiver_20261105.py|\
        tests/test_retired_legacy_delta_farm_20261111.py|\
        tests/test_priority_farm_deploy_20261112.py|\
        tests/test_main_service_panel.py|\
        tests/test_support_panel_links_deploy_20261111.py|\
        tests/test_recruit_examiner_panel_permissions_20261111.py) ;;
        *) echo "BLOCKED: file outside approved price/ticket scope: $path"; exit 2 ;;
    esac
done < <(git diff --name-only "$OLD_HEAD" "$TARGET")
if ! git diff --quiet "$OLD_HEAD" "$TARGET" -- requirements.txt web/requirements-web.txt; then
    echo "BLOCKED: dependency changes not permitted"
    exit 2
fi
echo "PASS: only approved release files changed"

echo "=== ONLINE SQLITE BACKUP (NO TABLE WRITES) ==="
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/priority_farm_ticket_$STAMP"
mkdir -p "$BACKUP"
MARKER="$APP/data/deployed_version.json"
if [[ -f "$MARKER" ]]; then cp -L "$MARKER" "$BACKUP/deployed_version.json"; fi
./venv/bin/python - "$BACKUP" <<'PY'
import sqlite3,sys
from pathlib import Path
target=Path(sys.argv[1])
for filename in ("bot.db","web_dashboard.db"):
    origin=Path.cwd()/filename
    if not origin.exists():
        raise SystemExit(f"BLOCKED: missing mandatory SQLite database {filename}")
    with sqlite3.connect(origin) as src, sqlite3.connect(target/filename) as dst:
        src.backup(dst)
    print("PASS: SQLite backup",filename)
PY

APPLIED=0
rollback() {
    result=$?
    trap - ERR
    if [[ "$APPLIED" == "1" ]]; then
        echo "DEPLOY FAILED - RESTORE CODE $OLD_HEAD"
        git reset --hard "$OLD_HEAD" || true
        if [[ -f "$BACKUP/deployed_version.json" ]]; then
            cp -L "$BACKUP/deployed_version.json" "$MARKER" || true
        fi
        systemctl restart "$BOT_SERVICE" "$WEB_SERVICE" || true
        systemctl is-active "$BOT_SERVICE" || true
        systemctl is-active "$WEB_SERVICE" || true
    fi
    echo "Backups retained: $BACKUP"
    exit "$result"
}
trap rollback ERR

echo "=== APPLY PINNED CODE AND PYTHON IMPORTS ==="
APPLIED=1
git checkout -B "$RELEASE_REF" "$TARGET"
./venv/bin/python -m compileall -q bot.py services views web/app
./venv/bin/python tools/runtime_import_smoke.py

echo "=== READ-ONLY PRIORITY MARGIN / DISCORD-WEB CONTRACT ==="
./venv/bin/python - <<'PY'
from services.order_rules import ORDER_RULES,calculate_price
from services.orders import get_order_item_details_for_group
from services.farm_fixed_cut_policy import (
    BASE_PUBLIC_FARM_FIXED_CUTS,PUBLIC_FARM_FIXED_CUTS,
    calculate_farm_fixed_cut_settlement
)
from services.self_service_financials import calculate_self_service_financials
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout
)
from services.quick_order_ticket_dedupe_policy import send_self_service_panel_once
from services.quick_order_v2 import _TICKET_DUPLICATE_WINDOW_SECONDS
from web.app.services.order_groups import get_grouped_order_catalog

assert len(BASE_PUBLIC_FARM_FIXED_CUTS)==10
assert len(PUBLIC_FARM_FIXED_CUTS)==20
groups={g["key"]:g for g in get_grouped_order_catalog("farm")}
for catalog,prefix,n in (
    ("ammo_dump","farm_ammo_dump_",12),("car_crash","farm_car_crash_",8)
):
    keys={x["rule_key"] for x in groups[catalog]["variants"]}
    expected={k for k in PUBLIC_FARM_FIXED_CUTS if k.startswith(prefix)}
    if keys!=expected or len(keys)!=n:
        raise SystemExit(f"BLOCKED: Web external priority options missing in {catalog}")
for key,(price,cut) in BASE_PUBLIC_FARM_FIXED_CUTS.items():
    base=calculate_farm_fixed_cut_settlement(key,price)
    hurry=calculate_farm_fixed_cut_settlement(key+"_rush",price+280)
    if (hurry.worker_amount-base.worker_amount!=280 or
        base.fixed_store_cut!=hurry.fixed_store_cut or
        base.customer_service_amount!=hurry.customer_service_amount or
        base.store_retained_amount!=hurry.store_retained_amount):
        raise SystemExit(f"BLOCKED: external priority commission mismatch: {key}")
    rule=ORDER_RULES[key+"_rush"]
    finance=calculate_self_service_financials(
        rule,calculate_price(rule,quantity=1),{}
    )
    if (finance["customer_pay_amount"]!=price+280 or
        finance["payout_base_amount"]!=hurry.worker_amount):
        raise SystemExit(f"BLOCKED: public Bot price or worker payout mismatch {key}")
    payout=calculate_one_companion_one_guard_order_payout(
        rule_key=key+"_rush",total_amount=hurry.worker_amount,
        worker_roles=[("check-worker","booster")],
        customer_service_total_amount=price+280,
    )
    if payout.worker_payouts[0].final_payout!=hurry.worker_amount or payout.customer_service_payout!=hurry.customer_service_amount:
        raise SystemExit(f"BLOCKED: payroll payout mismatch {key}")
for k,named,price,worker,cs in (
    ("staff_internal_ammo_dump_500m_rush",True,2910,2910,0),
    ("staff_internal_ammo_dump_500m_rush",False,3260,2910,88),
    ("staff_internal_car_500m_rush",None,2740,2740,0),
):
    rule=ORDER_RULES[k]
    data={"staff_internal_ammo_named":named} if named is not None else {}
    f=calculate_self_service_financials(rule,calculate_price(rule,quantity=1),data)
    if f["customer_pay_amount"]!=price or f["payout_base_amount"]!=worker:
        raise SystemExit(f"BLOCKED: internal priority finance mismatch {k} named={named}")
    p=calculate_one_companion_one_guard_order_payout(
        rule_key=k,total_amount=worker,worker_roles=[("worker","booster")],
        customer_service_total_amount=price,
    )
    if p.worker_payouts[0].final_payout!=worker or p.customer_service_payout!=cs:
        raise SystemExit(f"BLOCKED: internal priority payout mismatch {k}")
assert len(get_order_item_details_for_group("staff_internal","倒子彈｜500M"))==2
assert len(get_order_item_details_for_group("staff_internal","撞車｜500M"))==2
assert callable(send_self_service_panel_once)
assert _TICKET_DUPLICATE_WINDOW_SECONDS==20
print("PASS: 10 public normal + 10 public priority options; worker-only 280T")
print("PASS: internal named/unnamed/car worker-only 260T; old CS/margin unchanged")
print("PASS: ticket selector idempotency and quick-confirm dedupe installed")
PY

echo "=== RESTART BOT + WEB AND VERIFY HEALTH ==="
systemctl restart "$BOT_SERVICE" "$WEB_SERVICE"
ready=0
for attempt in $(seq 1 55); do
    if systemctl is-active --quiet "$BOT_SERVICE" &&
       systemctl is-active --quiet "$WEB_SERVICE" &&
       curl --fail --silent --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
        ready=1
        break
    fi
    sleep 2
done
if [[ "$ready" != 1 ]]; then
    echo "BLOCKED: services or Web health did not recover after restart"
    false
fi
systemctl is-active --quiet "$BOT_SERVICE"
systemctl is-active --quiet "$WEB_SERVICE"

APPLIED=0
trap - ERR
echo "DEPLOY COMPLETED: +260 internal and +280 public priority are worker-only; duplicate self-service panels prevented"
echo "Commit: $TARGET"
echo "Database backup: $BACKUP"
