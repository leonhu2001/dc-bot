#!/usr/bin/env bash
# Safe isolated Nov 10 VALORANT/LoL/APEX/Steam game pricing + public entry view release.
set -Eeuo pipefail

APP=/opt/dc-bot
RELEASE_REF=feat/nov10-lol-apex-steam-pricing-remove-public-price-button
PREVIOUS_RELEASE=4386dddf1da66adb01d55a5ffdf4df42749912e2
OPTIONAL_ACCOUNTING_RELEASE=922cfc686f2cfe329db5bdadfb87c64e70e0b13b
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
    "$PREVIOUS_RELEASE"|"$OPTIONAL_ACCOUNTING_RELEASE") ;;
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
        services/game_price_policy_20261023.py|\
        services/quick_order_v2_price_lists.py|\
        services/quick_order_v2_production.py|\
        services/orders.py|\
        services/loyalty_benefits.py|\
        web/app/services/order_groups.py|\
        web/app/services/accounting_reconciliation_policy.py|\
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
from services.order_rules import ORDER_RULES, calculate_price
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
for key,price in expected.items():
    if ORDER_RULES[key].price!=price:
        raise SystemExit(f"BLOCKED: live {key} expected {price}T, got {ORDER_RULES[key].price}T")
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
            if rule.price!=base+steps*50 or rule.unit_label!="局":
                raise SystemExit(f"BLOCKED: bad {game} customer rank tier: {rule.key}")
            if calculate_price(rule,quantity=2,player_count=2).base_amount!=rule.price*4:
                raise SystemExit(f"BLOCKED: {game} tier total mismatch: {rule.key}")
        web=next(g for g in get_grouped_order_catalog(game) if g["key"]==prefix)
        discord=get_order_item_details_for_group(game,web["label"].split("｜")[-1])
        # LoL technical ARAM is an existing extra DC offering, kept for old users.
        expected_rows=len(tiers)+2
        if len(web["variants"])!=expected_rows or len(discord)<expected_rows:
            raise SystemExit(f"BLOCKED: missing customer tier options: {prefix}")
for prefix,base in (
    ("apex_entertain",350),("apex_diamond",400),
    ("apex_master",450),("apex_predator",550),
):
    for tier,step in (("diamond",1),("master",2),("predator",3)):
        rule=ORDER_RULES[f"{prefix}_ranked_tier_{tier}"]
        if rule.price!=base+step*50:
            raise SystemExit(f"BLOCKED: bad Apex tier {rule.key}")
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
    "branch":"feat/nov10-lol-apex-steam-pricing-remove-public-price-button",
    "deployed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "subject":"Final four game posters, customer ranks and Delta button retained",
    "status":"success",
},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
APPLIED=0
trap - ERR
echo
echo "DEPLOY COMPLETED: VALORANT/LoL/APEX/Steam prices updated; Delta price list preserved"
echo "Commit: $TARGET"
echo "Database backup: $BACKUP"
