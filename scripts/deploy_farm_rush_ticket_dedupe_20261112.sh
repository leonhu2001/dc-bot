#!/usr/bin/env bash
# CI-gated 2026-11-12 rush wash + duplicate-ticket-panel release.
# No past order or payroll rows are rewritten. All SQLite files backed up.
set -Eeuo pipefail
APP=/opt/dc-bot
RELEASE_REF=fix/quick-ticket-duplicate-and-farm-rush-fees-20261112
TARGET="${1:-}"
BOT_SERVICE=dc-bot.service
WEB_SERVICE=dc-bot-dashboard.service
if [[ -z "$TARGET" || "$(id -u)" -ne 0 ]]; then
  echo "Usage: root bash deploy_farm_rush_ticket_dedupe_20261112.sh TARGET"; exit 2
fi
cd "$APP"
OLD_HEAD="$(git rev-parse HEAD)"
case "$OLD_HEAD" in
  ed70f897a1dc4178922df8296cb6d1395acf61f5|\
  b179aa72b50400ccf01d80840e145dbdb2e6accc|\
  a34a2fb0046568b66a7a295132c2444f63e338d7) ;;
  *) echo "BLOCKED: unexpected deployed HEAD $OLD_HEAD"; exit 2;;
esac
DIRTY="$(git status --porcelain --untracked-files=all |
  grep -vE '^\?\? (data/(deployed_version|market_poll_state)\.json|web/app/static/images/payment/(cathay_qr|jkopay_qr)\.jpg)$' || true)"
if [[ -n "$DIRTY" ]]; then
  echo "BLOCKED: unexpected changes in VPS working tree"
  printf '%s\n' "$DIRTY"; exit 2
fi
echo "=== PINNED RELEASE AND GITHUB CI ==="
git fetch origin "+refs/heads/$RELEASE_REF:refs/remotes/origin/$RELEASE_REF"
if [[ "$(git rev-parse "origin/$RELEASE_REF")" != "$TARGET" ]]; then
  echo "BLOCKED: target SHA does not match branch HEAD"; exit 2
fi
RUNS="$(curl --fail --silent --show-error --max-time 25 \
  -H 'Accept: application/vnd.github+json' \
  -H 'User-Agent: mowan-safe-farm-rush' \
  "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$TARGET&per_page=20")"
printf '%s' "$RUNS" | ./venv/bin/python -c '
import json,sys
sha,branch=sys.argv[1:3]
runs=json.load(sys.stdin).get("workflow_runs",[])
ok=any(r.get("head_sha")==sha and r.get("head_branch")==branch
  and r.get("name")=="CI" and r.get("event")=="push"
  and r.get("status")=="completed" and r.get("conclusion")=="success"
  for r in runs)
if not ok: raise SystemExit("BLOCKED: exact release CI has not passed")
print("PASS: pinned CI successful")
' "$TARGET" "$RELEASE_REF"

echo "=== ALLOWLIST CHANGE SCOPE ==="
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$file" in
    .github/workflows/ci.yml|\
    bot.py|\
    scripts/deploy_support_panel_links_20261111.ps1|\
    scripts/deploy_support_panel_links_20261111.sh|\
    scripts/deploy_farm_rush_ticket_dedupe_20261112.sh|\
    scripts/deploy_farm_rush_ticket_dedupe_20261112.ps1|\
    services/farm_fixed_cut_policy.py|\
    services/one_companion_one_guard_payout.py|\
    services/order_rules.py|\
    services/orders.py|\
    services/quick_order_v2.py|\
    services/quick_order_v2_price_lists.py|\
    services/quick_order_ticket_policy_20261028.py|\
    services/self_service_financial_breakdown_display.py|\
    services/self_service_financials.py|\
    services/self_service_panel_dedupe.py|\
    services/self_service_ui_runtime.py|\
    services/staff_internal_ammo_dump_policy.py|\
    services/staff_internal_ammo_dump_ui.py|\
    tests/test_coin_wash_aw_exclusive_receiver_20261105.py|\
    tests/test_farm_rush_worker_only_20261112.py|\
    tests/test_internal_ammo_named_pricing_20261105.py|\
    tests/test_main_service_panel.py|\
    tests/test_public_farm_fixed_cut_20261111.py|\
    tests/test_quick_ticket_single_panel_20261112.py|\
    tests/test_recruit_examiner_panel_permissions_20261111.py|\
    tests/test_retired_legacy_delta_farm_20261111.py|\
    tests/test_staff_internal_delta_orders_20261105.py|\
    tests/test_support_panel_links_deploy_20261111.py|\
    tests/test_deploy_farm_rush_ticket_dedupe_20261112.py|\
    views/panels.py|\
    web/app/services/order_groups.py) ;;
    *) echo "BLOCKED: unauthorized changed path $file"; exit 2;;
  esac
done < <(git diff --name-only "$OLD_HEAD" "$TARGET")
if git diff --quiet "$OLD_HEAD" "$TARGET" -- services/farm_fixed_cut_policy.py; then
  echo "BLOCKED: rush policy unchanged"; exit 2
fi

echo "=== SAFE SQLITE BACKUPS ==="
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/rush_wash_dedupe_$STAMP"
mkdir -p "$BACKUP"
for name in bot.db web_dashboard.db; do
  if [[ ! -f "$name" ]]; then
    echo "BLOCKED: required database missing: $name"; exit 2
  fi
  ./venv/bin/python - "$name" "$BACKUP/$name" <<'PY'
import sqlite3,sys
src,dest=sys.argv[1:3]
with sqlite3.connect(src) as connection:
    with sqlite3.connect(dest) as backup:
        connection.backup(backup)
    result=connection.execute("PRAGMA quick_check").fetchone()
    if result!=( "ok", ):
        raise SystemExit(f"BLOCKED: integrity check failed on {src}: {result}")
print(f"PASS: SQLite backed up and checked: {src}")
PY
done

APPLIED=0
rollback() {
  code=$?
  trap - ERR
  if [[ "$APPLIED" == "1" ]]; then
    echo "DEPLOY FAILED - ROLLBACK TO $OLD_HEAD"
    git reset --hard "$OLD_HEAD" || true
    systemctl restart "$BOT_SERVICE" || true
    systemctl restart "$WEB_SERVICE" || true
    systemctl is-active "$BOT_SERVICE" || true
    systemctl is-active "$WEB_SERVICE" || true
  fi
  echo "Backup retained: $BACKUP"
  exit "$code"
}
trap rollback ERR
echo "=== APPLY CODE (NO LEDGER WRITES) ==="
git checkout -B "$RELEASE_REF" "$TARGET"
APPLIED=1
./venv/bin/python -m compileall -q bot.py services web/app/services

echo "=== READ-ONLY PRICE, PAYROLL AND CATALOG CHECKS ==="
./venv/bin/python - <<'PY'
from services.farm_fixed_cut_policy import (
    _BASE_PUBLIC_FARM_FIXED_CUTS, PUBLIC_FARM_FIXED_CUTS,
    calculate_farm_fixed_cut_settlement,
)
from services.order_rules import ORDER_RULES,calculate_price
from services.orders import get_order_item_details_for_group
from services.self_service_financials import calculate_self_service_financials
from services.staff_internal_ammo_dump_policy import NAMED_SELECTION_KEY
from services.one_companion_one_guard_payout import (
    is_full_worker_payout_rule,calculate_one_companion_one_guard_order_payout,
)
from web.app.services.order_groups import get_grouped_order_catalog
from services.self_service_panel_dedupe import ensure_single_self_service_panel
assert len(_BASE_PUBLIC_FARM_FIXED_CUTS)==10
assert len(PUBLIC_FARM_FIXED_CUTS)==20
web={group["key"]:group for group in get_grouped_order_catalog("farm")}
for category, prefix, group_name, count in (
    ("ammo_dump","farm_ammo_dump_","倒子彈代肝",6),
    ("car_crash","farm_car_crash_","撞車代肝",4),
):
    bot_keys={x["rule_key"] for x in get_order_item_details_for_group("farm",group_name)}
    web_keys={x["rule_key"] for x in web[category]["variants"]}
    assert bot_keys==web_keys and len(bot_keys)==count*2
for key,(price,cut) in _BASE_PUBLIC_FARM_FIXED_CUTS.items():
    normal=calculate_farm_fixed_cut_settlement(key,price)
    rush_key=key+"_rush"
    rush=calculate_farm_fixed_cut_settlement(rush_key,price+280)
    assert ORDER_RULES[rush_key].price==price+280
    assert rush.fixed_store_cut==normal.fixed_store_cut==cut
    assert rush.worker_amount==normal.worker_amount+280
    assert rush.customer_service_amount==normal.customer_service_amount
    assert rush.store_retained_amount==normal.store_retained_amount
    assert is_full_worker_payout_rule(rush_key)
for key,named,charge,wage,margin,cs in (
    ("staff_internal_ammo_dump_500m_rush",True,2910,2910,0,0),
    ("staff_internal_ammo_dump_500m_rush",False,3260,2910,350,88),
    ("staff_internal_car_500m_rush",None,2740,2740,0,0),
):
    rule=ORDER_RULES[key]
    quote=calculate_self_service_financials(
        rule,calculate_price(rule,quantity=1),{NAMED_SELECTION_KEY:named})
    assert (quote["customer_pay_amount"],quote["payout_base_amount"],
            quote.get("store_margin_amount",0),
            quote.get("customer_service_payout_amount",0))==(charge,wage,margin,cs)
    result=calculate_one_companion_one_guard_order_payout(
        rule_key=key,total_amount=wage,
        worker_roles=[("check-worker","booster")],
        customer_service_total_amount=charge)
    assert result.total_worker_payout==wage and result.customer_service_payout==cs
assert callable(ensure_single_self_service_panel)
print("PASS: 10+10 public tiers, internal named/unnamed/car rush, worker wages, stable shop/CS cuts and dedupe")
PY

echo "=== RESTART BOT + WEB ==="
systemctl restart "$BOT_SERVICE"
systemctl restart "$WEB_SERVICE"
systemctl is-active --quiet "$BOT_SERVICE"
systemctl is-active --quiet "$WEB_SERVICE"
READY=0
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error --max-time 3 \
    http://127.0.0.1:8000/health 2>/dev/null | ./venv/bin/python -c '
import json,sys
try:
    result=json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if result.get("ok") is True and
    result.get("database") is True and result.get("public_assets") is True else 1)
' >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 1
done
if [[ "$READY" != "1" ]]; then
  echo "BLOCKED: Web health check timed out"; false
fi
systemctl is-active --quiet "$BOT_SERVICE"
systemctl is-active --quiet "$WEB_SERVICE"
APPLIED=0
trap - ERR
echo "DEPLOY COMPLETED: duplicate self-service panel guarded; internal +260T/public +280T rush fully paid to worker"
echo "Commit: $TARGET"
echo "Database backup: $BACKUP"
