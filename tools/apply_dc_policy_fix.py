from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, got {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, repl: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: regex expected one match, got {count}: {pattern[:100]!r}")
    write(path, updated)


def insert_async_function_tail(path: str, function_name: str, block: str, marker: str) -> None:
    text = read(path)
    if marker in text:
        return

    tree = ast.parse(text)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{path}: expected one async {function_name}, got {len(matches)}")

    node = matches[0]
    lines = text.splitlines()
    insert_at = int(node.end_lineno or 0)
    if node.body and isinstance(node.body[-1], (ast.Return, ast.Raise)):
        insert_at = int(node.body[-1].lineno or insert_at) - 1

    indent = " " * (int(node.col_offset or 0) + 4)
    rendered = [indent + line if line else "" for line in block.strip("\n").splitlines()]
    lines[insert_at:insert_at] = ["", *rendered]
    write(path, "\n".join(lines) + ("\n" if text.endswith("\n") else ""))


# ---------------------------------------------------------------------------
# 1) Centralize shared Discord infrastructure IDs and dispatch cadence.
# ---------------------------------------------------------------------------
write(
    "core/discord_settings.py",
    '''"""Shared Discord infrastructure settings.

Keep IDs/cadence that are consumed by multiple runtimes here so Discord, Web,
and tests cannot silently drift apart. Business/catalog rules remain in their
own domain modules.
"""

GENERAL_MANAGER_ROLE_ID = 1537067761141030972

DASHBOARD_ADMIN_ROLE_IDS = {
    "1131128849443328030",
    "1482084782031638548",
}

DASHBOARD_WORKER_ROLE_IDS = {
    "1503701170504339458",
    "1503706721883783218",
}

SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60
SMART_DISPATCH_SECOND_WAVE_SECONDS = 240
SMART_DISPATCH_FULL_EXPANSION_SECONDS = 420
SMART_DISPATCH_REPEAT_REMINDER_SECONDS = 600
SMART_DISPATCH_LOOP_SECONDS = 10

DISPATCH_ACTIVE_TIMEOUT_SECONDS = 90
DISPATCH_RECENT_TIMEOUT_SECONDS = 300
''',
)

replace_once(
    "core/permissions.py",
    "import discord\n\n\n# 總管：客服之上的整店管理層。即使舊 bot.py 仍把歷史 MANAGER_ROLE_ID\n# 指向客服，這個固定角色仍可作為客服權限的 superset 使用。\nGENERAL_MANAGER_ROLE_ID = 1537067761141030972\n",
    "import discord\n\nfrom core.discord_settings import GENERAL_MANAGER_ROLE_ID\n",
)

write(
    "shared/discord_roles.py",
    '''from core.discord_settings import (
    DASHBOARD_ADMIN_ROLE_IDS as ADMIN_ROLE_IDS,
    DASHBOARD_WORKER_ROLE_IDS as WORKER_ROLE_IDS,
)


def has_admin_role(role_ids: list[str] | set[str]) -> bool:
    roles = {str(role_id) for role_id in role_ids}
    return bool(roles & ADMIN_ROLE_IDS)


def has_worker_role(role_ids: list[str] | set[str]) -> bool:
    roles = {str(role_id) for role_id in role_ids}
    return bool(roles & WORKER_ROLE_IDS)


def get_dashboard_access(role_ids: list[str] | set[str]) -> dict:
    return {
        "is_admin": has_admin_role(role_ids),
        "is_worker": has_worker_role(role_ids),
    }
''',
)

replace_once(
    "views/smart_dispatch.py",
    '''SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60
# 保留第一版智慧派單節奏：公開開放後 3 分鐘擴大一批、6 分鐘全量通知。
SECOND_WAVE_AFTER_OPEN_SECONDS = 180
FULL_EXPANSION_AFTER_OPEN_SECONDS = 360
SECOND_WAVE_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + SECOND_WAVE_AFTER_OPEN_SECONDS
FULL_EXPANSION_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + FULL_EXPANSION_AFTER_OPEN_SECONDS
REPEAT_REMINDER_SECONDS = 600
SMART_DISPATCH_LOOP_SECONDS = 10
''',
    '''from core.discord_settings import (
    SMART_DISPATCH_ALERT_CHANNEL_ID,
    SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS as PUBLIC_ACCEPTANCE_OPEN_SECONDS,
    SMART_DISPATCH_SECOND_WAVE_SECONDS as SECOND_WAVE_SECONDS,
    SMART_DISPATCH_FULL_EXPANSION_SECONDS as FULL_EXPANSION_SECONDS,
    SMART_DISPATCH_REPEAT_REMINDER_SECONDS as REPEAT_REMINDER_SECONDS,
    SMART_DISPATCH_LOOP_SECONDS,
)

# 保留操作語意：公開開放後 3 分鐘擴大一批、6 分鐘全量通知。
SECOND_WAVE_AFTER_OPEN_SECONDS = SECOND_WAVE_SECONDS - PUBLIC_ACCEPTANCE_OPEN_SECONDS
FULL_EXPANSION_AFTER_OPEN_SECONDS = FULL_EXPANSION_SECONDS - PUBLIC_ACCEPTANCE_OPEN_SECONDS
''',
)

replace_once(
    "services/smart_dispatch.py",
    '''from services.dispatch_presence import get_online_dispatch_worker_ids

TAIPEI_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)
FIRST_EXPANSION_SECONDS = 180
FULL_EXPANSION_SECONDS = 360
''',
    '''from core.discord_settings import (
    SMART_DISPATCH_SECOND_WAVE_SECONDS,
    SMART_DISPATCH_FULL_EXPANSION_SECONDS,
)
from services.dispatch_presence import (
    get_online_dispatch_worker_ids,
    get_recent_dispatch_worker_ids,
)

TAIPEI_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)
# 兩個 runtime 共用「從訂單建立起算」的時間，避免 180/360 與
# 240/420 兩套語意再次漂移。
FIRST_EXPANSION_SECONDS = SMART_DISPATCH_SECOND_WAVE_SECONDS
FULL_EXPANSION_SECONDS = SMART_DISPATCH_FULL_EXPANSION_SECONDS
''',
)

replace_once(
    "services/smart_dispatch.py",
    '''    online = set(
        get_online_dispatch_worker_ids(
            candidate_ids=deduped,
            db_file=db_file,
            now=now_taipei,
        )
    )
''',
    '''    active_online = set(
        get_online_dispatch_worker_ids(
            candidate_ids=deduped,
            db_file=db_file,
            now=now_taipei,
        )
    )
    recent_online = set(
        get_recent_dispatch_worker_ids(
            candidate_ids=deduped,
            db_file=db_file,
            now=now_taipei,
        )
    )
''',
)

replace_once(
    "services/smart_dispatch.py",
    '''            0 if worker_id in online else 1,
            0 if worker_id in priority else 1,
''',
    '''            # 活躍（90 秒內）優先，其次保留 5 分鐘內曾在大廳的人，
            # 避免切分頁/短暫斷線就立刻被當成完全離線。
            0 if worker_id in active_online else 1,
            0 if worker_id in recent_online else 1,
            0 if worker_id in priority else 1,
''',
)

replace_once(
    "services/dispatch_presence.py",
    '''from typing import Iterable

DEFAULT_ONLINE_TIMEOUT_SECONDS = 90
MIN_TOUCH_INTERVAL_SECONDS = 20
''',
    '''from typing import Iterable

from core.discord_settings import (
    DISPATCH_ACTIVE_TIMEOUT_SECONDS,
    DISPATCH_RECENT_TIMEOUT_SECONDS,
)

DEFAULT_ONLINE_TIMEOUT_SECONDS = DISPATCH_ACTIVE_TIMEOUT_SECONDS
RECENT_ONLINE_TIMEOUT_SECONDS = DISPATCH_RECENT_TIMEOUT_SECONDS
MIN_TOUCH_INTERVAL_SECONDS = 20
''',
)

presence_anchor = '''def count_online_dispatch_workers(
    *,
    timeout_seconds: int = DEFAULT_ONLINE_TIMEOUT_SECONDS,
'''
presence_text = read("services/dispatch_presence.py")
if "def get_recent_dispatch_worker_ids(" not in presence_text:
    idx = presence_text.find(presence_anchor)
    if idx < 0:
        raise RuntimeError("services/dispatch_presence.py: count_online anchor not found")
    helper = '''def get_recent_dispatch_worker_ids(
    *,
    candidate_ids: Iterable[str | int] | None = None,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return workers seen within the wider 5-minute recent-presence window."""
    return get_online_dispatch_worker_ids(
        timeout_seconds=RECENT_ONLINE_TIMEOUT_SECONDS,
        candidate_ids=candidate_ids,
        db_file=db_file,
        now=now,
    )


def classify_dispatch_presence(
    candidate_ids: Iterable[str | int],
    *,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Classify candidates as active, recent, or offline.

    active: <= 90 seconds; recent: > 90 seconds and <= 5 minutes; offline: older.
    """
    ids = list(dict.fromkeys(
        str(item)
        for item in candidate_ids
        if str(item).strip()
    ))
    active = set(get_online_dispatch_worker_ids(
        candidate_ids=ids,
        db_file=db_file,
        now=now,
    ))
    recent = set(get_recent_dispatch_worker_ids(
        candidate_ids=ids,
        db_file=db_file,
        now=now,
    ))
    return {
        worker_id: (
            "active"
            if worker_id in active
            else "recent"
            if worker_id in recent
            else "offline"
        )
        for worker_id in ids
    }


'''
    write("services/dispatch_presence.py", presence_text[:idx] + helper + presence_text[idx:])

# Expose both active and recent counts to the Web dispatch state API. Existing
# UI/Discord green count remains active-only, while clients can distinguish the
# wider recent pool without redefining "online".
replace_once(
    "web/app/routers/dispatch_state.py",
    '''from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
''',
    '''from services.dispatch_presence import (
    RECENT_ONLINE_TIMEOUT_SECONDS,
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
''',
)
replace_once(
    "web/app/routers/dispatch_state.py",
    '''    return {
        "online_companion_count": count_online_dispatch_workers(),
        "online_support_count": len(get_online_dispatch_support_ids()),
    }
''',
    '''    active_count = count_online_dispatch_workers()
    recent_total = count_online_dispatch_workers(
        timeout_seconds=RECENT_ONLINE_TIMEOUT_SECONDS,
    )
    return {
        "online_companion_count": active_count,
        "recent_companion_count": max(active_count, recent_total),
        "recent_only_companion_count": max(0, recent_total - active_count),
        "online_support_count": len(get_online_dispatch_support_ids()),
    }
''',
)

# ---------------------------------------------------------------------------
# 2) Specified-DM failures: keep the slot reserved, but surface the failure to
#    the staff alert channel so support can act instead of silently waiting.
# ---------------------------------------------------------------------------
smart_view = read("views/smart_dispatch.py")
if "async def _notify_specified_dispatch_failure(" not in smart_view:
    anchor = "async def send_specified_staff_dispatch_dms(\n"
    idx = smart_view.find(anchor)
    if idx < 0:
        raise RuntimeError("views/smart_dispatch.py: specified-DM function anchor not found")
    helper = '''async def _notify_specified_dispatch_failure(
    guild: discord.Guild,
    *,
    staff_id: str,
    reason: str,
    dispatch_jump_url: str,
) -> None:
    alert_channel = guild.get_channel(SMART_DISPATCH_ALERT_CHANNEL_ID)
    if alert_channel is None or not callable(getattr(alert_channel, "send", None)):
        return

    try:
        await alert_channel.send(
            "⚠️ **指定陪玩通知異常**\\n"
            f"指定人員：<@{staff_id}>\\n"
            f"原因：{reason}\\n"
            "指定名額仍會保留，請客服確認是否需要聯絡本人或調整訂單。\\n"
            f"前往原派單：{dispatch_jump_url}",
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )
    except (discord.Forbidden, discord.HTTPException):
        return


'''
    smart_view = smart_view[:idx] + helper + smart_view[idx:]
    write("views/smart_dispatch.py", smart_view)

replace_once(
    "views/smart_dispatch.py",
    '''        if member is None:
            failed.append(staff_id)
            continue
''',
    '''        if member is None:
            failed.append(staff_id)
            await _notify_specified_dispatch_failure(
                guild,
                staff_id=staff_id,
                reason="找不到伺服器成員",
                dispatch_jump_url=dispatch_jump_url,
            )
            continue
''',
)
replace_once(
    "views/smart_dispatch.py",
    '''        if not role_ids_match_requirements(
            member_role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            failed.append(staff_id)
            continue
''',
    '''        if not role_ids_match_requirements(
            member_role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            failed.append(staff_id)
            await _notify_specified_dispatch_failure(
                guild,
                staff_id=staff_id,
                reason="目前不符合此訂單的職位／遊戲資格",
                dispatch_jump_url=dispatch_jump_url,
            )
            continue
''',
)
replace_once(
    "views/smart_dispatch.py",
    '''        except (discord.Forbidden, discord.HTTPException):
            failed.append(staff_id)

    return sent, failed
''',
    '''        except (discord.Forbidden, discord.HTTPException):
            failed.append(staff_id)
            await _notify_specified_dispatch_failure(
                guild,
                staff_id=staff_id,
                reason="Discord 私訊無法送達",
                dispatch_jump_url=dispatch_jump_url,
            )

    return sent, failed
''',
)

# ---------------------------------------------------------------------------
# 3) VIP whitelist video/stream permission + startup sweep for all tracked
#    existing VIP rooms.
# ---------------------------------------------------------------------------
voice_text = read("views/voice.py")
voice_old = '''def build_vip_whitelist_overwrite() -> discord.PermissionOverwrite:
    """白名單最小權限：可見、進語音、說話、在語音聊天室打字。"""
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        stream=False,
'''
voice_new = '''def build_vip_whitelist_overwrite() -> discord.PermissionOverwrite:
    """白名單權限：可見、進語音、說話、開視訊/直播、在語音聊天室打字。"""
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        stream=True,
'''
if voice_text.count(voice_old) != 1:
    raise RuntimeError("views/voice.py: VIP whitelist overwrite pattern drifted")
voice_text = voice_text.replace(voice_old, voice_new, 1)

if "async def sync_all_existing_vip_whitelist_permissions(" not in voice_text:
    anchor = '''        await grant_vip_whitelist_access(voice_channel, member)\n\n\ndef build_play_lobby_overwrites'''
    if anchor not in voice_text:
        raise RuntimeError("views/voice.py: whitelist sync insertion anchor not found")
    helper = '''        await grant_vip_whitelist_access(voice_channel, member)\n\n\nasync def sync_all_existing_vip_whitelist_permissions(\n    guild: discord.Guild,\n) -> int:\n    """Re-apply whitelist permissions to every tracked existing VIP room.\n\n    This is intentionally idempotent and is run on bot ready so permission\n    policy changes (such as enabling video/stream) reach rooms that were\n    created before the deploy.\n    """\n    try:\n        from core.database import list_vip_voice_rooms\n    except Exception:\n        return 0\n\n    updated = 0\n    for row in list_vip_voice_rooms():\n        try:\n            owner_id = int(row.get("owner_id") or 0)\n            channel_id = int(row.get("channel_id") or 0)\n        except (AttributeError, TypeError, ValueError):\n            continue\n        if not owner_id or not channel_id:\n            continue\n\n        channel = guild.get_channel(channel_id)\n        if not isinstance(channel, discord.VoiceChannel):\n            continue\n\n        await sync_vip_whitelist_permissions(channel, owner_id)\n        updated += 1\n\n    return updated\n\n\ndef build_play_lobby_overwrites'''
    voice_text = voice_text.replace(anchor, helper, 1)
write("views/voice.py", voice_text)

replace_once(
    "bot.py",
    '''    sync_vip_whitelist_permissions,\n)\n''',
    '''    sync_vip_whitelist_permissions,\n    sync_all_existing_vip_whitelist_permissions,\n)\n''',
)

insert_async_function_tail(
    "bot.py",
    "on_ready",
    '''# VIP_POLICY_STARTUP_SYNC_V1\ntry:\n    vip_sync_guild = bot.get_guild(GUILD_ID)\n    if vip_sync_guild is not None:\n        await sync_all_existing_vip_whitelist_permissions(vip_sync_guild)\nexcept Exception as exc:\n    print(f"[VIP] failed to refresh existing VIP whitelist permissions: {exc}")''',
    "VIP_POLICY_STARTUP_SYNC_V1",
)

# ---------------------------------------------------------------------------
# 4) Public service rules: objective complaint criteria + cancellation/refund
#    matrix + auditable blacklist policy.
# ---------------------------------------------------------------------------
replace_once(
    "web/app/templates/service_rules.html",
    "規章版本：2026-09-02-v1",
    "規章版本：2026-10-10-v2",
)
replace_once(
    "web/app/templates/service_rules.html",
    '''                <strong>不接受技術性客訴</strong>，
                但仍可針對態度、掛機、擺爛等問題申訴。
''',
    '''                陪玩單不以勝率、擊殺數、段位結果或單次操作失誤
                作為技術性賠付依據；但無故掛機、拒絕履行訂單內容、
                明顯消極服務、擅自提前離開、辱罵或騷擾，
                仍屬服務問題，可提出客訴。
''',
)
replace_once(
    "web/app/templates/service_rules.html",
    '''                闆闆須配合合理指揮，
                禁止故意送死、亂跑、藏物或卡保底。
''',
    '''                闆闆須配合與完成訂單直接相關、且不違反遊戲規範的合理指揮。
                若因自行脫隊、拒絕撤離、故意暴露位置、
                藏取本應交付的訂單物資等可明確認定行為造成失敗，
                該局得不列入補償或保底計算；有爭議時以錄影與訂單紀錄由客服判定。
''',
)
replace_once(
    "web/app/templates/service_rules.html",
    '''                <strong>不接受技術性客訴</strong>。
''',
    '''                不接受僅以遊戲勝負或技術表現為由的賠付；
                若未依訂單指定玩法、故意妨礙流程，
                或出現掛機、提前離場、辱罵等服務問題，仍可申訴。
''',
)
replace_once(
    "web/app/templates/service_rules.html",
    '''                偽造證據或惡意客訴
''',
    '''                偽造證據，或明知內容不實仍提出客訴／刻意剪輯紀錄誤導判定
''',
)

rules_text = read("web/app/templates/service_rules.html")
if "⏸️ 中斷、取消與退款" not in rules_text:
    anchor = '''    <section class="service-rules-card">\n\n        <h2>\n            💬 售後\n        </h2>'''
    if anchor not in rules_text:
        raise RuntimeError("service_rules.html: after-sales anchor not found")
    section = '''    <section class="service-rules-card">\n\n        <h2>\n            ⏸️ 中斷、取消與退款\n        </h2>\n\n        <ul>\n            <li>\n                <strong>顧客原因：</strong>服務開始後由顧客主動取消、無故離開或失聯，\n                已完成的時間／局數照常計算；未履行部分由客服依可否改期、補回或退款處理。\n            </li>\n\n            <li>\n                <strong>陪玩／打手原因：</strong>若人員遲到、失聯、擅自離場或無法完成約定內容，\n                顧客可選擇換人、補時／補打，或退回尚未履行的服務；\n                責任人員薪資原則上僅計實際合格完成部分。\n            </li>\n\n            <li>\n                <strong>店家調度原因：</strong>若本店無法依約提供服務，\n                可免費改期、換人，或退回尚未履行部分。\n            </li>\n\n            <li>\n                <strong>遊戲維護、伺服器異常或其他不可抗力：</strong>\n                以暫停、改期、補打或退回尚未履行部分為原則；\n                已正常完成的服務不因後續中斷而回溯退款。\n            </li>\n\n            <li>\n                退款原則以<strong>尚未履行的服務</strong>為範圍；\n                若客服依錄影、對話及訂單紀錄確認有重大服務瑕疵，得另行補償。\n            </li>\n        </ul>\n\n    </section>\n\n\n'''
    rules_text = rules_text.replace(anchor, section + anchor, 1)

if "黑名單處分將記錄原因" not in rules_text:
    old = '''        <p class="service-rules-important">\n            嚴重違規者，本店有權終止服務並列入黑名單。\n        </p>\n'''
    new = '''        <p class="service-rules-important">\n            嚴重違規者，本店有權終止服務並列入黑名單。\n            黑名單處分將記錄原因及相關訂單／證據，原則分為 30 日、90 日及永久；\n            重複違規、詐欺、外掛、嚴重騷擾或惡意退款等情節重大者得直接永久處分。\n            當事人可於通知後 7 日內向客服提出一次申訴，由未參與原判定的人員複核。\n        </p>\n'''
    if old not in rules_text:
        raise RuntimeError("service_rules.html: blacklist paragraph not found")
    rules_text = rules_text.replace(old, new, 1)
write("web/app/templates/service_rules.html", rules_text)

# ---------------------------------------------------------------------------
# 5) Regression tests for the new policy invariants.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_vip_room_whitelist.py",
    "    assert overwrite.stream is False\n",
    "    assert overwrite.stream is True\n",
)

write(
    "tests/test_dispatch_policy_consistency.py",
    '''from datetime import datetime, timedelta, timezone

from core.discord_settings import (
    DISPATCH_ACTIVE_TIMEOUT_SECONDS,
    DISPATCH_RECENT_TIMEOUT_SECONDS,
    SMART_DISPATCH_FULL_EXPANSION_SECONDS,
    SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS,
    SMART_DISPATCH_REPEAT_REMINDER_SECONDS,
    SMART_DISPATCH_SECOND_WAVE_SECONDS,
)
from services.dispatch_presence import classify_dispatch_presence
from views import smart_dispatch


def test_dispatch_cadence_has_one_source_of_truth():
    assert smart_dispatch.PUBLIC_ACCEPTANCE_OPEN_SECONDS == SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS == 60
    assert smart_dispatch.SECOND_WAVE_SECONDS == SMART_DISPATCH_SECOND_WAVE_SECONDS == 240
    assert smart_dispatch.FULL_EXPANSION_SECONDS == SMART_DISPATCH_FULL_EXPANSION_SECONDS == 420
    assert smart_dispatch.REPEAT_REMINDER_SECONDS == SMART_DISPATCH_REPEAT_REMINDER_SECONDS == 600


def test_presence_windows_are_active_then_recent():
    assert DISPATCH_ACTIVE_TIMEOUT_SECONDS == 90
    assert DISPATCH_RECENT_TIMEOUT_SECONDS == 300
    assert DISPATCH_ACTIVE_TIMEOUT_SECONDS < DISPATCH_RECENT_TIMEOUT_SECONDS


def test_presence_classifier_keeps_short_disconnect_as_recent(monkeypatch):
    from services import dispatch_presence

    monkeypatch.setattr(
        dispatch_presence,
        "get_online_dispatch_worker_ids",
        lambda **kwargs: ["A"],
    )
    monkeypatch.setattr(
        dispatch_presence,
        "get_recent_dispatch_worker_ids",
        lambda **kwargs: ["A", "B"],
    )

    result = classify_dispatch_presence(["A", "B", "C"])
    assert result == {"A": "active", "B": "recent", "C": "offline"}
''',
)

write(
    "tests/test_service_rules_policy.py",
    '''from pathlib import Path


def test_public_rules_define_objective_complaint_and_refund_policy():
    text = Path("web/app/templates/service_rules.html").read_text(encoding="utf-8")

    assert "規章版本：2026-10-10-v2" in text
    assert "不以勝率、擊殺數、段位結果或單次操作失誤" in text
    assert "顧客原因" in text
    assert "陪玩／打手原因" in text
    assert "店家調度原因" in text
    assert "不可抗力" in text
    assert "尚未履行的服務" in text
    assert "30 日、90 日及永久" in text
    assert "7 日內" in text
''',
)

write(
    "tests/test_vip_whitelist_startup_sync.py",
    '''from pathlib import Path

from views.voice import build_vip_whitelist_overwrite


def test_vip_whitelist_can_use_video_stream():
    assert build_vip_whitelist_overwrite().stream is True


def test_bot_ready_runs_existing_vip_room_permission_sweep():
    text = Path("bot.py").read_text(encoding="utf-8")
    assert "sync_all_existing_vip_whitelist_permissions" in text
    assert "VIP_POLICY_STARTUP_SYNC_V1" in text
''',
)

# Ensure the migration changed source rather than leaving a runtime patcher.
for temp_path in (
    ROOT / ".github/workflows/one_time_dc_policy_fix.yml",
    ROOT / "tools/apply_dc_policy_fix.py",
):
    if temp_path.exists():
        temp_path.unlink()

print("DC policy source migration applied successfully")
