#!/usr/bin/env bash
# Isolated release: no October/November price-change code is present.
set -Eeuo pipefail

APP="/opt/dc-bot"
BASE="d637f16412d15bb8bc77229d105c7816b35da06d"
REF="feat/payment-qrs-profile-tips-only-20261109"
TARGET="${1:-}"
BOT="dc-bot.service"
WEB="dc-bot-dashboard.service"

[[ "$(id -u)" == 0 ]] || { echo "FAIL: must run as root"; exit 2; }
[[ "$TARGET" =~ ^[a-f0-9]{40}$ ]] || { echo "FAIL: invalid target SHA"; exit 2; }
cd "$APP"

OLD="$(git rev-parse HEAD)"
[[ "$OLD" == "$BASE" ]] || {
  echo "BLOCKED: VPS is at $OLD, not validated baseline $BASE."
  echo "No changes made. Do not replace newer live code with this isolated release."
  exit 3
}
git diff --quiet || { echo "BLOCKED: tracked VPS files have local edits"; exit 3; }
git diff --cached --quiet || { echo "BLOCKED: VPS index has local edits"; exit 3; }

git fetch origin "$REF"
[[ "$(git rev-parse "FETCH_HEAD")" == "$TARGET" ]] || {
  echo "BLOCKED: target is not the approved tip/QR branch head"; exit 3;
}
git merge-base --is-ancestor "$BASE" "$TARGET" || {
  echo "BLOCKED: unrelated history"; exit 3;
}

# Fail closed if the isolated branch ever modifies product prices or promotions.
if git diff --name-only "$BASE" "$TARGET" | grep -Eq   '^(services/(order_rules|orders|quick_order_v2_price_lists|one_companion_one_guard_catalog|one_companion_one_guard_payout)\.py|web/app/services/checkout_preview\.py)$'; then
  echo "BLOCKED: unexpected pricing/catalog changes in feature release"; exit 3
fi
for filename in cathay_qr.jpg jkopay_qr.jpg; do
  test -s "$APP/web/app/static/images/payment/$filename" || {
    echo "BLOCKED: VPS missing payment QR image: $filename"; exit 3
  }
done

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/payment_only_$STAMP"
mkdir -p "$BACKUP"
for filename in web_dashboard.db bot_data.json data/deployed_version.json; do
  if [[ -f "$APP/$filename" ]]; then
    mkdir -p "$BACKUP/$(dirname "$filename")"
    cp -p "$APP/$filename" "$BACKUP/$filename"
  fi
done
printf '%s\n' "$OLD" > "$BACKUP/old_head.txt"
printf '%s\n' "$TARGET" > "$BACKUP/target_head.txt"

RESTORE_NEEDED=0
rollback() {
  local status=$?
  trap - ERR
  if [[ "$RESTORE_NEEDED" == 1 ]]; then
    echo "DEPLOY FAILED: restoring original source $OLD"
    git switch --detach "$OLD" || true
    systemctl restart "$WEB" "$BOT" || true
  fi
  exit "$status"
}
trap rollback ERR

echo "=== ISOLATED QR/TIP DEPLOY (NO PRICE CHANGES) ==="
RESTORE_NEEDED=1
systemctl stop "$BOT" "$WEB"
git switch --detach "$TARGET"
"$APP/venv/bin/python" -m compileall -q bot.py services views web/app
"$APP/venv/bin/python" "$APP/tools/runtime_import_smoke.py"
"$APP/venv/bin/python" - <<'PY'
from services.order_rules import get_rule
expected = {
    'basic_entertain_single': 320,
    'basic_one_companion_one_guard_secret': 720,
    'basic_one_companion_one_guard_topsecret': 770,
    'basic_tech_secret_single': 400,
    'basic_tech_topsecret_single': 450,
    'basic_trial_500': 450,
    'basic_trial_1000': 900,
}
for key, old_price in expected.items():
    assert get_rule(key).price == old_price, (
        f"unexpected price for {key}: {get_rule(key).price} != {old_price}"
    )
print("PASS: previous Delta desktop prices remain unchanged")
PY
systemctl start "$WEB" "$BOT"
sleep 3
for unit in "$WEB" "$BOT"; do
  systemctl is-active --quiet "$unit" || {
    echo "FAIL: $unit not active"; false
  }
done
RESTORE_NEEDED=0
trap - ERR
mkdir -p "$APP/data"
printf '{"kind":"payment_qr_profile_tips_only","commit":"%s","base":"%s"}\n' \
  "$TARGET" "$BASE" > "$APP/data/payment_only_release.json"
echo "DEPLOY COMPLETE: $TARGET"
echo "Prices unchanged; backup: $BACKUP"
