#!/usr/bin/env bash
# Safely update ONLY the existing Discord customer-service lobby panel.
# No SQLite, payroll, order-rule, game price, or Web files are modified.
set -Eeuo pipefail

APP=/opt/dc-bot
BOT_SERVICE=dc-bot.service
RELEASE_REF=feat/welcome-order-navigation-sync-20261111
PREVIOUS_RELEASE=ed70f897a1dc4178922df8296cb6d1395acf61f5
PREVIOUS_PANEL_RELEASE=b179aa72b50400ccf01d80840e145dbdb2e6accc
TARGET="${1:-}"

if [[ -z "$TARGET" || "$(id -u)" -ne 0 ]]; then
    echo "Usage: root bash deploy_support_panel_links_20261111.sh TARGET"
    exit 2
fi
cd "$APP"
OLD_HEAD="$(git rev-parse HEAD)"
if [[ "$OLD_HEAD" != "$PREVIOUS_RELEASE" && "$OLD_HEAD" != "$PREVIOUS_PANEL_RELEASE" ]]; then
    echo "BLOCKED: unexpected VPS HEAD $OLD_HEAD (expected $PREVIOUS_RELEASE)"
    exit 2
fi
DIRTY="$(git status --porcelain --untracked-files=all |
    grep -vE '^\?\? (data/(deployed_version|market_poll_state)\.json|web/app/static/images/payment/(cathay_qr|jkopay_qr)\.jpg)$' || true)"
if [[ -n "$DIRTY" ]]; then
    echo "BLOCKED: unexpected edits in VPS working tree"
    printf '%s\n' "$DIRTY"
    exit 2
fi

echo "=== PINNED PANEL RELEASE / CI CHECK ==="
git fetch origin "+refs/heads/$RELEASE_REF:refs/remotes/origin/$RELEASE_REF"
if [[ "$(git rev-parse "origin/$RELEASE_REF")" != "$TARGET" ]]; then
    echo "BLOCKED: target does not match approved branch HEAD"
    exit 2
fi
RUNS="$(curl --fail --silent --show-error --max-time 20 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: mw-support-panel-safe-deploy' \
    "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$TARGET&per_page=20")"
printf '%s' "$RUNS" | ./venv/bin/python -c '
import json,sys
target,branch=sys.argv[1:3]
runs=json.load(sys.stdin).get("workflow_runs",[])
valid=[r for r in runs if r.get("name")=="CI" and r.get("event")=="push"
       and r.get("head_sha")==target and r.get("head_branch")==branch
       and r.get("status")=="completed" and r.get("conclusion")=="success"]
if not valid:
    raise SystemExit("BLOCKED: exact panel release CI not successful")
print("PASS: exact panel release CI passed")
' "$TARGET" "$RELEASE_REF"

echo "=== PANEL-ONLY SCOPE GUARD ==="
while IFS= read -r changed; do
    [[ -z "$changed" ]] && continue
    case "$changed" in
        .github/workflows/ci.yml|\
        views/panels.py|\
        views/welcome.py|\
        tests/test_welcome_message.py|\
        tests/test_main_service_panel.py|\
        tests/test_support_panel_links_deploy_20261111.py|\
        scripts/deploy_support_panel_links_20261111.sh|\
        scripts/deploy_support_panel_links_20261111.ps1) ;;
        *) echo "BLOCKED: unauthorized file modified by panel release: $changed"; exit 2 ;;
    esac
done < <(git diff --name-only "$OLD_HEAD" "$TARGET")
if git diff --quiet "$OLD_HEAD" "$TARGET" -- views/welcome.py; then
    echo "BLOCKED: welcome text did not change"
    exit 2
fi

echo "=== BACKUP CURRENT PANEL SOURCE ==="
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/_archive/support_panel_links_$STAMP"
mkdir -p "$BACKUP"
cp -p views/panels.py "$BACKUP/panels.py"
cp -p views/welcome.py "$BACKUP/welcome.py"
echo "PASS: original panel source backed up: $BACKUP"

APPLIED=0
rollback() {
    code=$?
    trap - ERR
    if [[ "$APPLIED" == "1" ]]; then
        echo "DEPLOY FAILED - ROLLBACK TO $OLD_HEAD"
        git reset --hard "$OLD_HEAD" || true
        systemctl restart "$BOT_SERVICE" || true
        systemctl is-active "$BOT_SERVICE" || true
    fi
    exit "$code"
}
trap rollback ERR

echo "=== APPLY CODE AND VERIFY ORIGINAL BUTTONS ==="
git checkout -B "$RELEASE_REF" "$TARGET"
APPLIED=1
./venv/bin/python -m py_compile views/panels.py views/welcome.py
# Production venv intentionally does not need pytest: CI already executed the
# full suite; this runtime precheck only imports the actual embed and buttons.
./venv/bin/python - <<'PY'
from views.panels import build_main_panel_embed,MainPanelView
from views.welcome import build_welcome_description
embed=build_main_panel_embed()
description=embed.description or ""
welcome=build_welcome_description("<@123456789>")
expected=("1569412217269395597","1562940108246753331",
          "1562940127976890509","1562940161313087498",
          "1562940249171042415","1562940146632888450")
assert all(description.count("<#"+cid+">")==1 for cid in expected)
assert all(welcome.count("<#"+cid+">")==1 for cid in expected)
assert len(MainPanelView().children)==4
print("PASS: six same channel links in welcome and panel, four persistent buttons")
PY

echo "=== RESTART BOT ONLY (WEB AND DATABASES UNTOUCHED) ==="
systemctl restart "$BOT_SERVICE"
ready=0
for attempt in $(seq 1 45); do
    if systemctl is-active --quiet "$BOT_SERVICE"; then
        ready=1
        break
    fi
    sleep 1
done
if [[ "$ready" != "1" ]]; then
    echo "BLOCKED: Bot service did not become active"
    false
fi

echo "=== VERIFY ORIGINAL DISCORD MESSAGE IN PLACE ==="
# Make the edit deterministic: the bot also edits this same message on_ready,
# and this API check guarantees the linked text is actually on Discord.
# PATCH only embeds, never components, so the four persistent buttons survive.
./venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from views.panels import MainPanelView, build_main_panel_embed
from views.welcome import build_welcome_description,build_welcome_embed,extract_welcome_member_mention

load_dotenv(dotenv_path=".env")
token=os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("BLOCKED: DISCORD_TOKEN unavailable for panel verification")

channel_id="1497622678138519572"
message_id="1537533276884045856"
# Match bot.py's configured panel IDs without importing core.config (which
# can migrate/write config.json). This is strictly read-only.
settings_path=Path("config.json")
if settings_path.exists():
    try:
        settings=json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings,dict):
            raise ValueError("config must be an object")
        channel_id=str(int(settings.get("DISPATCH_SUPPORT_ONLINE_CHANNEL_ID") or channel_id))
        message_id=str(int(settings.get("MAIN_SERVICE_PANEL_MESSAGE_ID") or message_id))
    except (ValueError,TypeError,OSError) as error:
        raise SystemExit("BLOCKED: cannot resolve configured support panel IDs")
base="https://discord.com/api/v10"
headers={
    "Authorization": "Bot "+token,
    "User-Agent": "DiscordBot (https://github.com/leonhu2001/dc-bot, 1.0)",
    "Accept": "application/json",
}

def request(method, path, payload=None):
    request_headers=dict(headers)
    data=None
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"]="application/json"
    try:
        with urlopen(
            Request(base+path,data=data,headers=request_headers,method=method),
            timeout=18,
        ) as response:
            return json.load(response)
    except HTTPError as error:
        raise SystemExit(f"BLOCKED: Discord API {method} HTTP {error.code}")
    except (URLError,TimeoutError) as error:
        raise SystemExit(f"BLOCKED: Discord API {method} unavailable ({type(error).__name__})")

def button_ids(message):
    return {
        item.get("custom_id")
        for row in message.get("components",[])
        for item in row.get("components",[])
        if item.get("custom_id")
    }

expected_buttons={
    item.custom_id
    for item in MainPanelView().children
    if getattr(item,"custom_id",None)
}
assert len(expected_buttons)==4
me=request("GET","/users/@me")
path=f"/channels/{channel_id}/messages/{message_id}"
before=request("GET",path)
if str(before.get("author",{}).get("id"))!=str(me.get("id")):
    raise SystemExit("BLOCKED: target panel is not authored by this Bot")
if not before.get("embeds") or before["embeds"][0].get("title")!="魔丸娛樂｜聯絡客服":
    raise SystemExit("BLOCKED: target message is not the expected support panel")
if button_ids(before)!=expected_buttons:
    raise SystemExit("BLOCKED: target message's four existing buttons differ")

embed=build_main_panel_embed().to_dict()
description=embed["description"]
for channel in (
    "1569412217269395597",
    "1562940108246753331",
    "1562940127976890509",
    "1562940161313087498",
    "1562940249171042415",
    "1562940146632888450",
):
    if description.count(f"<#{channel}>")!=1:
        raise SystemExit(f"BLOCKED: price/order channel link missing or repeated: {channel}")

request("PATCH",path,{"embeds":[embed]})
after=request("GET",path)
if not after.get("embeds") or after["embeds"][0].get("description")!=description:
    raise SystemExit("BLOCKED: original Discord panel text did not update")
if button_ids(after)!=expected_buttons:
    raise SystemExit("BLOCKED: original Discord panel buttons changed")
print("PASS: original support panel updated on Discord with all six links")
print("PASS: original four buttons retained; no duplicate panel created")
PY

systemctl is-active --quiet "$BOT_SERVICE"
APPLIED=0
trap - ERR
echo "DEPLOY COMPLETED: welcome and existing support panel link to all game order channels and price list"
echo "Commit: $TARGET"
echo "Original panel source backup: $BACKUP"
