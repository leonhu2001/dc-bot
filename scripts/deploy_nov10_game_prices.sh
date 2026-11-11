#!/usr/bin/env bash
# Safe isolated Nov 10 VALORANT/LoL/APEX/Steam game pricing + public entry view release.
set -Eeuo pipefail

APP=/opt/dc-bot
RELEASE_REF=fix/retire-mouth-organ-and-old-halfcoin-20261111
PREVIOUS_RELEASE=4386dddf1da66adb01d55a5ffdf4df42749912e2
OPTIONAL_ACCOUNTING_RELEASE=922cfc686f2cfe329db5bdadfb87c64e70e0b13b
PREVIOUS_POSTER_RELEASE=558fe84f6842a799a375f996a699eb1c4362ab79
PREVIOUS_ADMIN_RELEASE=6bfca436e2cb41ff4df6014a32311ada53cc018f
PREVIOUS_SALARY_RELEASE=eb6179d6e2a6083a8a18cc81e652e2924abd266a
PREVIOUS_FARM_RELEASE=0f0ea2d600c04efc27b16b5db33b0801a1ec8ed2
TARGET="${1:-}"
BOT_SERVICE=dc-bot.service
WEB_SERVICE=dc-bot-dashboard.service

if [[ -z "$TARGET" || "$(id -u)" -ne 0 ]]; then
    echo "Usage: root bash deploy_nov10_game_prices.sh TARGET"
    exit 2
fi
cd "$APP"
OLD_HEAD="$(git rev-parse HEAD)"
case "$OLD_HEAD" in
    "$PREVIOUS_RELEASE"|"$OPTIONAL_ACCOUNTING_RELEASE"|"$PREVIOUS_POSTER_RELEASE"|"$PREVIOUS_ADMIN_RELEASE"|"$PREVIOUS_SALARY_RELEASE"|"$PREVIOUS_FARM_RELEASE") ;;
    *) echo "BLOCKED: Unexpected deployed HEAD $OLD_HEAD"; exit 2 ;;
esac

DIRTY="$(
    git status --porcelain --untracked-files=all |
    grep -vE '^\?\? (data/(deployed_version|market_poll_state)\.json|web/app/static/images/payment/(cathay_qr|jkopay_qr)\.jpg)$' ||
    true
)"
if [[ -n "$DIRTY" ]]; then
    echo "BLOCKED: VPS working tree is not clean"
    printf '%s\n' "$DIRTY"
    exit 2
fi

echo "=== ISOLATED RELEASE AND CI PRECHECK ==="
git fetch origin "+refs/heads/$RELEASE_REF:refs/remotes/origin/$RELEASE_REF"
if [[ "$(git rev-parse "origin/$RELEASE_REF")" != "$TARGET" ]]; then
    echo "BLOCKED: target is not the exact owner-approved release head"
    exit 2
fi
RUNS="$(curl --fail --silent --show-error --max-time 20 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: mw-nov10-price-safe-deploy' \
    "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$TARGET&per_page=20")"
printf '%s' "$RUNS" | ./venv/bin/python -c '
import json,sys
target,branch=sys.argv[1:3]
runs=json.load(sys.stdin).get("workflow_runs",[])
valid=[r for r in runs if r.get("name")=="CI" and r.get("event")=="push"
       and r.get("head_sha")==target and r.get("head_branch")==branch]
if not valid or valid[0].get("status")!="completed" or valid[0].get("conclusion")!="success":
    raise SystemExit("BLOCKED: exact release push CI not successful")
print("PASS: pinned release CI passed")
' "$TARGET" "$RELEASE_REF"

echo "=== SCOPE GUARD ==="
while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    case "$file" in
        .github/workflows/ci.yml|\
        services/order_rules.py|\
        services/order_product_status.py|\
        web/app/services/public_checkout.py|\
        tests/test_retired_legacy_delta_farm_20261111.py|\
        tests/test_deploy_farm_scope_preflight_20261111.py|\
        services/farm_fixed_cut_policy.py|\
        services/self_service_financials.py|\
        services/one_companion_one_guard_payout.py|\
        web/app/services/checkout_preview.py|\
        web/app/services/order_service.py|\
        web/app/services/worker_bonus_payout.py|\
        web/app/services/accounting_reconciliation.py|\
        tests/test_public_farm_fixed_cut_20261111.py|\
        tests/test_coin_wash_aw_exclusive_receiver_20261105.py|\
        tests/test_delta_farm_price_lists_20261102.py|\
        tests/test_delta_farm_price_lists_20261102.py|\
        services/game_price_policy_20261023.py|\
        services/quick_order_v2_price_lists.py|\
        services/quick_order_v2_production.py|\
        services/orders.py|\
        services/loyalty_benefits.py|\
        web/app/services/order_groups.py|\
        web/app/services/accounting_reconciliation_policy.py|\
        web/app/routers/admin_order_rules.py|\
        web/app/services/worker_performance.py|\
        web/app/static/js/pages/employee_center.js|\
        web/app/static/css/pages/employee_center.css|\
        web/app/templates/employee_center.html|\
        tests/test_payout_summary_performance_policy.py|\
        tests/test_employee_salary_dashboard.py|\
        tests/e2e/test_employee_salary_pagination.py|\
        web/app/templates/admin_order_rules.html|\
        tests/test_admin_order_rules_every_product_20261110.py|\
        tests/test_game_service_rules.py|\
        tests/test_quick_order_v2_patch_ownership.py|\
        tests/test_point_benefit_catalog_v2.py|\
        tests/test_loyalty_companion_fix_20261029.py|\
        tests/test_loyalty_companion_count.py|\
        tests/test_dynamic_game_point_benefits.py|\
        tests/test_companion_count_finish_20261028.py|\
        tests/test_apex_pricing_20261012.py|\
        tests/test_quick_order_v2_price_lists.py|\
        tests/test_quick_order_v2_public_view_policy.py|\
        tests/test_web_catalog_parity_20261029.py|\
        tests/test_nov10_game_price_alignment.py|\
        tests/test_verified_nov_bonus_accounting_alerts_20261110.py|\
        scripts/deploy_verified_nov_bonus_accounting_20261110.sh|\
        scripts/deploy_nov10_game_prices.ps1|\
        scripts/deploy_nov10_game_prices.sh)
            ;;
        *) echo "BLOCKED: unexpected file changed: $file"; exit 2 ;;
    esac
done < <(git diff --name-only "$OLD_HEAD" "$TARGET")
if ! git diff --quiet "$OLD_HEAD" "$TARGET" -- requirements.txt web/requirements-web.txt; then
    echo "BLOCKED: dependencies unexpectedly changed"
    exit 2
fi

# Compare all non-target source definitions before any live service is stopped.
# This explicitly prevents Delta, sweet and teaching rule drift.
./venv/bin/python - "$OLD_HEAD" "$TARGET" <<'PY'
import subprocess,sys,types
from dataclasses import asdict
from pathlib import Path
old_sha,new_sha=sys.argv[1:3]
# CRITICAL: services.__init__ imports order_rules, which imports the
# farm module. Registering an empty farm placeholder first triggered the
# circular-import failure on the VPS. Importing the live services package
# instead is also unsafe here: it installs runtime patches and can initialize
# SQLite. Create an isolated import-only namespace for the two pure helper
# modules used by order_rules, without executing services.__init__ or Bot/Web.
package=types.ModuleType("services")
package.__path__=[str(Path.cwd()/"services")]
package.__package__="services"
sys.modules["services"]=package
# The old VPS may predate the fixed-cut module, so load the exact pinned
# target source into this isolated namespace before rule comparisons.
farm_name="services.farm_fixed_cut_policy"
farm_src=subprocess.check_output(
    ["git","show",f"{new_sha}:services/farm_fixed_cut_policy.py"],text=True
)
farm_mod=types.ModuleType(farm_name); sys.modules[farm_name]=farm_mod
exec(compile(farm_src,"services/farm_fixed_cut_policy.py","exec"),farm_mod.__dict__)
new_farm_keys=set(farm_mod.PUBLIC_FARM_FIXED_CUTS)
def base_rules(commit):
    source=subprocess.check_output(
        ["git","show",f"{commit}:services/order_rules.py"], text=True
    )
    name=f"_nov10_price_guard_{commit[:10]}"
    m=types.ModuleType(name); sys.modules[name]=m
    exec(compile(source,"services/order_rules.py","exec"),m.__dict__)
    return m._BASE_ORDER_RULES
old=base_rules(old_sha); new=base_rules(new_sha)
for key, rule in old.items():
    if rule.category in {"valorant","steam","lol","apex"}:
        continue
    if key not in new or asdict(rule)!=asdict(new[key]):
        raise SystemExit(f"BLOCKED: unrelated rule changed: {key}")
for key in new:
    if key not in old and new[key].category not in {"valorant","steam","lol","apex"}:
        if key not in new_farm_keys or new[key].category != "farm":
            raise SystemExit(f"BLOCKED: unrelated rule added: {key}")
print("PASS: every non-target game/order rule unchanged")
PY

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/nov10_games_$STAMP"
mkdir -p "$BACKUP"
MARKER="$APP/data/deployed_version.json"
if [[ -f "$MARKER" ]]; then
    cp -L "$MARKER" "$BACKUP/deployed_version.json"
fi
./venv/bin/python - "$BACKUP" <<'PY'
import sqlite3,sys
from pathlib import Path
root=Path.cwd(); backup=Path(sys.argv[1])
for name in ("bot.db","web_dashboard.db"):
    path=root/name
    if not path.exists():
        raise SystemExit(f"BLOCKED: required DB missing: {name}")
    with sqlite3.connect(path) as source, sqlite3.connect(backup/name) as target:
        source.backup(target)
    print(f"PASS: safe SQLite backup: {name}")
PY

APPLIED=0
rollback() {
    rc=$?
    trap - ERR
    if [[ "$APPLIED" == 1 ]]; then
        echo "DEPLOY FAILED - ROLLBACK TO $OLD_HEAD"
        git reset --hard "$OLD_HEAD" || true
        if [[ -f "$BACKUP/deployed_version.json" ]]; then
            cp -L "$BACKUP/deployed_version.json" "$MARKER" || true
        fi
        systemctl restart "$BOT_SERVICE" "$WEB_SERVICE" || true
        systemctl is-active "$BOT_SERVICE" || true
        systemctl is-active "$WEB_SERVICE" || true
    fi
    echo "Backup retained: $BACKUP"
    exit "$rc"
}
trap rollback ERR

echo "=== UPDATE CODE & COMPILE ==="
APPLIED=1
git checkout -B "$RELEASE_REF" "$TARGET"
./venv/bin/python -m compileall -q bot.py cogs core services shared views web/app tools scripts
./venv/bin/python tools/runtime_import_smoke.py

echo "=== READ-ONLY PRICE AND ACCOUNTING CONTRACT ==="
./venv/bin/python - <<'PY'
from pathlib import Path
from services.order_rules import ORDER_RULES, calculate_price, get_base_rule, OWNER_APPROVED_GAME_PRICE_REVISION
from services.order_rule_store import get_active_override
from services.orders import get_order_item_details_for_group
from web.app.services.order_groups import get_grouped_order_catalog
from services.quick_order_v2_production import _public_view_for_channel
from services.quick_order_v2 import QUICK_ORDER_V2_CHANNELS
from web.app.services.accounting_reconciliation_policy import (
    _connect_readonly, _is_verified_nov_bonus_repair,
    _policy_consistency_for_order,
)
expected={
    "valorant_entertain_ng":350,"valorant_entertain_ranked":280,
    "valorant_ascendant_ng":330,"valorant_ascendant_ranked":300,
    "valorant_immortal_ng":350,"valorant_immortal_ranked":330,
    "valorant_radiant_ng":380,"valorant_radiant_ranked":370,
    "lol_entertain_aram":350,"lol_entertain_ng":350,
    "lol_entertain_ranked":280,"lol_master_ng":380,
    "lol_master_ranked":300,"lol_grandmaster_ng":390,
    "lol_grandmaster_ranked":350,"lol_elite_ng":400,
    "lol_elite_ranked":430,
    "apex_entertain_ng":320,"apex_entertain_ranked":350,
    "apex_diamond_ng":380,"apex_diamond_ranked":400,
    "apex_master_ng":400,"apex_master_ranked":450,
    "apex_predator_ng":500,"apex_predator_ranked":550,
    "steam_play":350,
}
def assert_approved_price(key, poster_price):
    # Poster base values are immutable; a *new* explicit manager publish can
    # override them for future orders, while old unmarked overrides cannot.
    if get_base_rule(key).price != poster_price:
        raise SystemExit(f"BLOCKED: poster base price drifted: {key}")
    active = get_active_override(key)
    payload = (active or {}).get("payload") or {}
    actual = (
        int(payload.get("price", poster_price))
        if payload.get("_owner_price_revision") == OWNER_APPROVED_GAME_PRICE_REVISION
        else poster_price
    )
    if ORDER_RULES[key].price != actual:
        raise SystemExit(f"BLOCKED: published/active price differs for {key}")
for key,price in expected.items():
    assert_approved_price(key,price)
# Customer ranks are explicit service variants on both storefronts.
for game,prefixes,tiers in (
    ("valorant",
     (("valorant_entertain",280),("valorant_ascendant",300),
      ("valorant_immortal",330),("valorant_radiant",370)),
     ("diamond","ascendant","immortal","radiant")),
    ("lol",
     (("lol_entertain",280),("lol_master",300),
      ("lol_grandmaster",350),("lol_elite",430)),
     ("emerald","diamond","master","grandmaster","challenger")),
):
    for prefix,base in prefixes:
        for steps,tier in enumerate(tiers,1):
            rule=ORDER_RULES[f"{prefix}_ranked_tier_{tier}"]
            assert_approved_price(rule.key, base+steps*50)
            if rule.unit_label!="局":
                raise SystemExit(f"BLOCKED: bad {game} customer rank unit: {rule.key}")
            if calculate_price(rule,quantity=2,player_count=2).base_amount!=rule.price*4:
                raise SystemExit(f"BLOCKED: {game} tier total mismatch: {rule.key}")
        web=next(g for g in get_grouped_order_catalog(game) if g["key"]==prefix)
        discord=get_order_item_details_for_group(game,web["label"].split("｜")[-1])
        # Only LoL entertainment officially lists ARAM on Web; technical
        # ARAM is retained on Discord for historical customer selections.
        expected_web_keys={f"{prefix}_ng",f"{prefix}_ranked"} | {
            f"{prefix}_ranked_tier_{tier}" for tier in tiers
        }
        if game=="lol" and prefix=="lol_entertain":
            expected_web_keys.add(f"{prefix}_aram")
        expected_discord_keys=set(expected_web_keys)
        if game=="lol":
            expected_discord_keys.add(f"{prefix}_aram")
        web_keys={row["rule_key"] for row in web["variants"]}
        discord_keys={row["rule_key"] for row in discord}
        if web_keys!=expected_web_keys or discord_keys!=expected_discord_keys:
            raise SystemExit(
                f"BLOCKED: customer tier options mismatch: {prefix}; "
                f"web missing={sorted(expected_web_keys-web_keys)}, "
                f"web extra={sorted(web_keys-expected_web_keys)}, "
                f"discord missing={sorted(expected_discord_keys-discord_keys)}, "
                f"discord extra={sorted(discord_keys-expected_discord_keys)}"
            )
for prefix,base in (
    ("apex_entertain",350),("apex_diamond",400),
    ("apex_master",450),("apex_predator",550),
):
    for tier,step in (("diamond",1),("master",2),("predator",3)):
        rule=ORDER_RULES[f"{prefix}_ranked_tier_{tier}"]
        assert_approved_price(rule.key,base+step*50)
        if calculate_price(rule,quantity=2,player_count=2).base_amount!=rule.price*4:
            raise SystemExit(f"BLOCKED: Apex tier total mismatch {rule.key}")
    web=next(g for g in get_grouped_order_catalog("apex") if g["key"]==prefix)
    discord=get_order_item_details_for_group("apex",web["label"].split("｜")[-1])
    if len(web["variants"])!=5 or len(discord)!=5:
        raise SystemExit(f"BLOCKED: missing Apex options {prefix}")
for game in ("delta","valorant","lol","apex","steam"):
    channel=QUICK_ORDER_V2_CHANNELS[game]
    view=_public_view_for_channel(channel)
    has_price_button=any(
        str(getattr(x,"custom_id","")).startswith("quick_order_v2_price_list_")
        for x in view.children
    )
    if has_price_button!=(game=="delta"):
        raise SystemExit(f"BLOCKED: wrong public price-list button policy on {game}")
db=_connect_readonly(Path("web_dashboard.db"))
if db is None:
    raise SystemExit("BLOCKED: cannot read live salary DB")
try:
    for oid in (298,300):
        # This is a repricing release, never a payout-repair action.
        # Validate a prior approved repair if it exists, without demanding
        # an unrelated bookkeeping correction on an as-yet unpatched VPS.
        if _is_verified_nov_bonus_repair(db,oid):
            state=_policy_consistency_for_order(db,oid)
            if not (state["worker_consistent"] and state["cs_consistent"]):
                raise SystemExit(f"BLOCKED: protected 2% payout inconsistent #{oid}")
        else:
            print(f"NOTE: payout #{oid} has no verified repair audit; no salary write attempted")
finally:
    db.close()
print("PASS: prices, tier totals, Web/Discord options, Delta button preserved and read-only wage check")
PY

echo "=== READ-ONLY ADMIN ORDER RULES FULL-CATALOG AUDIT ==="
./venv/bin/python - <<'PY'
from services.order_rules import ORDER_RULES, preview_rule_override, rule_to_override_payload
from web.app.routers.admin_order_rules import _is_admin_editable_rule
from web.app.services.order_groups import get_grouped_order_catalog
total = 0
categories = set()
for key, rule in ORDER_RULES.items():
    if not _is_admin_editable_rule(key):
        continue
    try:
        preview = preview_rule_override(key, rule_to_override_payload(rule))
    except Exception as exc:
        raise SystemExit(f"BLOCKED: admin rule not editable: {key}: {exc}")
    if preview.key != key or preview.category != rule.category:
        raise SystemExit(f"BLOCKED: admin rule identity mismatch: {key}")
    total += 1
    categories.add(rule.category)
for game in ("valorant", "lol", "apex", "steam"):
    web = get_grouped_order_catalog(game)
    if not web:
        raise SystemExit(f"BLOCKED: Web missing {game} groups")
    for group in web:
        for variant in group["variants"]:
            key = variant["rule_key"]
            if key not in ORDER_RULES or variant["price"] != ORDER_RULES[key].price:
                raise SystemExit(f"BLOCKED: Web rule mismatch: {key}")
if total < 20 or not {"valorant","lol","apex","steam","farm","custom"}.issubset(categories):
    raise SystemExit(f"BLOCKED: admin catalog incomplete: {total} {sorted(categories)}")
print(f"PASS: {total} editable admin rules across {len(categories)} categories; Web rule data is consistent")
PY

echo "=== READ-ONLY MONTHLY PERFORMANCE AND SALARY CONTRACT ==="
./venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from web.app.services.worker_performance import build_worker_performance_map
from web.app.services.worker_tip_salary_sql import tip_earning_date_expr

month = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
db = "web_dashboard.db"
performance = build_worker_performance_map(db, month=month)
with sqlite3.connect("file:web_dashboard.db?mode=ro", uri=True) as conn:
    expected = {}
    for worker, amount in conn.execute("""
        SELECT CAST(p.worker_discord_id AS TEXT), p.final_payout
        FROM worker_payouts p
        JOIN web_orders w ON w.id = p.order_id
        WHERE w.status='closed'
          AND COALESCE(p.final_payout,0)>0
          AND COALESCE(p.worker_discord_id,'')<>''
          AND substr(COALESCE(NULLIF(w.closed_at,''),NULLIF(w.updated_at,''),
                              NULLIF(w.created_at,'')),1,7)=?
    """, (month,)):
        expected[worker] = expected.get(worker, 0) + int(round(float(amount or 0)))
    if expected != performance:
        raise SystemExit("BLOCKED: monthly performance differs from service-only wages")
    tips_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_tips'"
    ).fetchone()
    if tips_table:
        paid_tips = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount),0) FROM worker_tips WHERE payment_status='paid'"
        ).fetchone()
        print(f"PASS: paid tip records remain in payroll table ({paid_tips[0]} rows, {paid_tips[1]}T); not counted in performance")
print(f"PASS: {len(performance)} workers' service-only monthly performance validated ({month}); salary tables untouched")
PY

echo "=== PUBLIC FARM FIXED CUT CONTRACT (READ-ONLY) ==="
./venv/bin/python - <<'PY'
from services.farm_fixed_cut_policy import (
    PUBLIC_FARM_FIXED_CUTS,calculate_farm_fixed_cut_settlement,
)
from services.order_rules import ORDER_RULES,calculate_price
from services.orders import get_order_item_details_for_group
from services.one_companion_one_guard_payout import calculate_one_companion_one_guard_order_payout
from services.quick_order_v2_price_lists import DELTA_FARM_PRICE_LISTS
from web.app.services.order_groups import get_grouped_order_catalog

assert len(PUBLIC_FARM_FIXED_CUTS)==10
assert "night_population" not in DELTA_FARM_PRICE_LISTS
web={g["key"]:g for g in get_grouped_order_catalog("farm")}
for group,prefix in (("ammo_dump","farm_ammo_dump_"),("car_crash","farm_car_crash_")):
    expected={key for key in PUBLIC_FARM_FIXED_CUTS if key.startswith(prefix)}
    assert {x["rule_key"] for x in web[group]["variants"]}==expected
    discord=get_order_item_details_for_group("farm",web[group]["label"])
    assert {x["rule_key"] for x in discord}==expected
for key,(price,cut) in PUBLIC_FARM_FIXED_CUTS.items():
    rule=ORDER_RULES[key]
    if rule.price!=price or rule.required_staff_count!=1 or rule.allowed_roles!=("halfcoin_receiver",):
        raise SystemExit(f"BLOCKED: unexpected fixed farming price/role on {key}")
    if rule.vip_discount_allowed or rule.point_benefits_allowed or rule.loyalty_benefits_enabled:
        raise SystemExit(f"BLOCKED: fixed margin product has a discount: {key}")
    settlement=calculate_farm_fixed_cut_settlement(key,price)
    payout=calculate_one_companion_one_guard_order_payout(
        rule_key=key,total_amount=settlement.worker_amount,
        worker_roles=[("deploy-preview","booster")],
        customer_service_total_amount=price,
    )
    if (payout.worker_payouts[0].final_payout!=settlement.worker_amount
        or payout.customer_service_payout!=settlement.customer_service_amount
        or settlement.customer_service_amount+settlement.store_retained_amount!=cut):
        raise SystemExit(f"BLOCKED: fixed farm payout does not reconcile: {key}")
print("PASS: all 10 fixed store cuts, CS split, receiver role, Bot/Web options and mouth-organ removal verified")
PY

echo "=== RETIRED FARM PRODUCTS (READ-ONLY) ==="
./venv/bin/python - <<'PY'
from services.order_product_status import (
    RETIRED_LEGACY_FARM_RULE_KEYS, is_order_product_active,
    is_retired_legacy_farm_product, install_web_catalog_guards,
    install_discord_catalog_guards,
)
from services.order_rules import ORDER_RULES
from services import orders
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.public_checkout import build_public_quote
from web.app.routers.admin_order_rules import _is_admin_editable_rule
from services.quick_order_v2_price_lists import DELTA_FARM_PRICE_LISTS

install_web_catalog_guards()
install_discord_catalog_guards()
assert RETIRED_LEGACY_FARM_RULE_KEYS=={"farm_halfcoin_120m","farm_halfcoin_360m"}
assert all(key in ORDER_RULES and not is_order_product_active(key) for key in RETIRED_LEGACY_FARM_RULE_KEYS)
assert "night_population" not in DELTA_FARM_PRICE_LISTS
farm_groups=orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get("farm")
expired_groups=[label for label in farm_groups if orders.is_retired_farm_group("farm",label)]
if expired_groups:
    raise SystemExit(f"BLOCKED: retired farm groups still visible: {expired_groups!r}")
if not {"倒子彈代肝","撞車代肝"}.issubset(set(farm_groups)):
    raise SystemExit(f"BLOCKED: new public farm groups missing: {farm_groups!r}")
assert not any(_is_admin_editable_rule(key) for key in RETIRED_LEGACY_FARM_RULE_KEYS)
web=get_grouped_order_catalog("farm")
keys={v["rule_key"] for group in web for v in group["variants"]}
assert not RETIRED_LEGACY_FARM_RULE_KEYS.intersection(keys)
assert "halfcoin" not in {group["key"] for group in web}
assert "ammo_dump" in {group["key"] for group in web}
assert "car_crash" in {group["key"] for group in web}
for key in RETIRED_LEGACY_FARM_RULE_KEYS:
    try:
        build_public_quote(rule_key=key, quantity=1, player_count=1)
    except ValueError as e:
        if "停止提供" not in str(e) and "已下架" not in str(e):
            raise
    else:
        raise SystemExit(f"BLOCKED: retired product remains orderable: {key}")
for key in ("farm_ammo_dump_100m","farm_car_crash_100m","staff_internal_ammo_dump_500m"):
    assert not is_retired_legacy_farm_product(key)
print("PASS: old halfcoin and mouth-organ retired, Bot/Web/manager blocked, historical rules retained")
PY

echo "=== RESTART BOT + WEB ==="
systemctl restart "$BOT_SERVICE" "$WEB_SERVICE"
for service in "$BOT_SERVICE" "$WEB_SERVICE"; do
    ready=0
    for attempt in $(seq 1 25); do
        if systemctl is-active --quiet "$service"; then
            ready=1
            break
        fi
        sleep 1
    done
    if [[ "$ready" != 1 ]]; then
        echo "FAIL: $service not active"
        false
    fi
done

health=0
for attempt in $(seq 1 40); do
    if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health; then
        health=1
        break
    fi
    sleep 1
done
if [[ "$health" != 1 ]]; then
    echo "FAIL: website health check"
    false
fi

# If services have just transitioned to 'active', also verify a stable window.
for sample in $(seq 1 5); do
    sleep 2
    systemctl is-active --quiet "$BOT_SERVICE"
    systemctl is-active --quiet "$WEB_SERVICE"
done

./venv/bin/python - "$MARKER" "$TARGET" "$OLD_HEAD" <<'PY'
import json,sys
from pathlib import Path
from datetime import datetime,timezone
file=Path(sys.argv[1]); file.parent.mkdir(parents=True,exist_ok=True)
file.write_text(json.dumps({
    "commit":sys.argv[2],
    "previous_commit":sys.argv[3],
    "branch":"fix/retire-mouth-organ-and-old-halfcoin-20261111",
    "deployed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "subject":"Retire old mouth organ and halfcoin from new orders; preserve new ammo/car cuts",
    "status":"success",
},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
APPLIED=0
trap - ERR
echo
echo "DEPLOY COMPLETED: expired mouth-organ and legacy halfcoin removed from new orders; fixed-cut farming retained"
echo "Commit: $TARGET"
echo "Database backup: $BACKUP"
