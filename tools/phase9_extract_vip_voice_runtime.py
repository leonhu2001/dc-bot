from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot.py"
SERVICE = ROOT / "services" / "vip_voice_runtime.py"
TARGETS = [
    "member_has_vip_voice_role",
    "delete_vip_voice_room_for_owner",
    "restore_persistent_vip_voice_rooms",
]

source = BOT.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
nodes = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in TARGETS
}
missing = set(TARGETS) - nodes.keys()
if missing:
    raise RuntimeError(f"missing VIP voice runtime definitions: {sorted(missing)}")

blocks: list[str] = []
for name in TARGETS:
    node = nodes[name]
    text = "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n"
    if name == "member_has_vip_voice_role":
        text = text.replace(
            "if int(member.id) in {int(user_id) for user_id in HIDDEN_VIP_USER_IDS}:",
            "if int(member.id) in {int(user_id) for user_id in _HIDDEN_VIP_USER_IDS}:",
        )
    blocks.append(text)

header = '''from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import discord

from core.database import (
    delete_vip_voice_room_record,
    get_vip_voice_room_by_owner,
    list_vip_voice_rooms,
    upsert_vip_voice_room,
)


_CONFIGURED = False
_HIDDEN_VIP_USER_IDS: list[int] = []
VIP_VOICE_LOBBY_ROLE_IDS: list[int] = []
VIP_VOICE_LOBBY_CATEGORY_ID = 0
VIP_VOICE_CREATE_CHANNEL_NAME = ""
TEMP_VIP_VOICE_CHANNEL_IDS: set[int]
TEMP_VOICE_CONTROL_PANELS: dict
bot = None
fetch_member_safely: Callable
VoiceRoomControlView: Callable
delete_voice_control_panel: Callable[..., Awaitable]
sync_voice_control_panel_state_from_channel: Callable
sync_vip_whitelist_permissions: Callable[..., Awaitable]


def configure_vip_voice_runtime(
    *,
    bot_instance,
    hidden_vip_user_ids: list[int],
    vip_voice_role_ids: list[int],
    vip_voice_category_id: int,
    vip_voice_create_channel_name: str,
    temp_vip_channel_ids: set[int],
    temp_voice_control_panels: dict,
    fetch_member: Callable,
    control_view_factory: Callable,
    delete_control_panel: Callable[..., Awaitable],
    sync_control_panel_state: Callable,
    sync_whitelist_permissions: Callable[..., Awaitable],
) -> None:
    """Bind Discord/runtime collaborators for persistent VIP voice rooms."""
    global _CONFIGURED, _HIDDEN_VIP_USER_IDS
    global VIP_VOICE_LOBBY_ROLE_IDS, VIP_VOICE_LOBBY_CATEGORY_ID
    global VIP_VOICE_CREATE_CHANNEL_NAME, TEMP_VIP_VOICE_CHANNEL_IDS
    global TEMP_VOICE_CONTROL_PANELS, bot, fetch_member_safely
    global VoiceRoomControlView, delete_voice_control_panel
    global sync_voice_control_panel_state_from_channel, sync_vip_whitelist_permissions

    bot = bot_instance
    _HIDDEN_VIP_USER_IDS = [int(value) for value in hidden_vip_user_ids]
    VIP_VOICE_LOBBY_ROLE_IDS = [int(value) for value in vip_voice_role_ids]
    VIP_VOICE_LOBBY_CATEGORY_ID = int(vip_voice_category_id)
    VIP_VOICE_CREATE_CHANNEL_NAME = str(vip_voice_create_channel_name)
    TEMP_VIP_VOICE_CHANNEL_IDS = temp_vip_channel_ids
    TEMP_VOICE_CONTROL_PANELS = temp_voice_control_panels
    fetch_member_safely = fetch_member
    VoiceRoomControlView = control_view_factory
    delete_voice_control_panel = delete_control_panel
    sync_voice_control_panel_state_from_channel = sync_control_panel_state
    sync_vip_whitelist_permissions = sync_whitelist_permissions
    _CONFIGURED = True


def set_vip_voice_hidden_user_ids(user_ids: list[int]) -> None:
    global _HIDDEN_VIP_USER_IDS
    _HIDDEN_VIP_USER_IDS = [int(value) for value in user_ids]


'''
SERVICE.write_text(header + "\n\n".join(blocks), encoding="utf-8")

for node in sorted(nodes.values(), key=lambda item: item.lineno, reverse=True):
    del lines[node.lineno - 1 : node.end_lineno]
bot_source = "".join(lines)

import_anchor = '''from services.payment_review_runtime import ensure_payment_review_worker_started
'''
service_import = '''from services.vip_voice_runtime import (
    configure_vip_voice_runtime,
    set_vip_voice_hidden_user_ids,
    member_has_vip_voice_role,
    delete_vip_voice_room_for_owner,
    restore_persistent_vip_voice_rooms,
)
'''
if import_anchor not in bot_source:
    raise RuntimeError("bot service import anchor missing")
bot_source = bot_source.replace(import_anchor, import_anchor + service_import, 1)

refresh_anchor = '''    HIDDEN_VIP_USER_IDS = sorted(db_user_ids | configured_user_ids)
    set_hidden_vip_user_ids(HIDDEN_VIP_USER_IDS)
    return list(HIDDEN_VIP_USER_IDS)
'''
refresh_replacement = '''    HIDDEN_VIP_USER_IDS = sorted(db_user_ids | configured_user_ids)
    set_hidden_vip_user_ids(HIDDEN_VIP_USER_IDS)
    set_vip_voice_hidden_user_ids(HIDDEN_VIP_USER_IDS)
    return list(HIDDEN_VIP_USER_IDS)
'''
if refresh_anchor not in bot_source:
    raise RuntimeError("hidden VIP refresh anchor missing")
bot_source = bot_source.replace(refresh_anchor, refresh_replacement, 1)

bot_anchor = '''bot._extensions_loaded = False

# ========= Slash 指令群組 =========
'''
configure_block = '''bot._extensions_loaded = False

configure_vip_voice_runtime(
    bot_instance=bot,
    hidden_vip_user_ids=HIDDEN_VIP_USER_IDS,
    vip_voice_role_ids=VIP_VOICE_LOBBY_ROLE_IDS,
    vip_voice_category_id=VIP_VOICE_LOBBY_CATEGORY_ID,
    vip_voice_create_channel_name=VIP_VOICE_CREATE_CHANNEL_NAME,
    temp_vip_channel_ids=TEMP_VIP_VOICE_CHANNEL_IDS,
    temp_voice_control_panels=TEMP_VOICE_CONTROL_PANELS,
    fetch_member=fetch_member_safely,
    control_view_factory=VoiceRoomControlView,
    delete_control_panel=delete_voice_control_panel,
    sync_control_panel_state=sync_voice_control_panel_state_from_channel,
    sync_whitelist_permissions=sync_vip_whitelist_permissions,
)

# ========= Slash 指令群組 =========
'''
if bot_anchor not in bot_source:
    raise RuntimeError("bot initialization anchor missing")
bot_source = bot_source.replace(bot_anchor, configure_block, 1)
BOT.write_text(bot_source, encoding="utf-8")

# Physical-boundary regression.
test_path = ROOT / "tests" / "test_vip_voice_runtime_extraction.py"
test_path.write_text(
    '''from pathlib import Path


def test_vip_voice_lifecycle_is_owned_by_runtime_service():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    service = Path("services/vip_voice_runtime.py").read_text(encoding="utf-8")

    assert "def member_has_vip_voice_role" not in bot_source
    assert "async def delete_vip_voice_room_for_owner" not in bot_source
    assert "async def restore_persistent_vip_voice_rooms" not in bot_source
    assert "def member_has_vip_voice_role" in service
    assert "async def delete_vip_voice_room_for_owner" in service
    assert "async def restore_persistent_vip_voice_rooms" in service
    assert "def configure_vip_voice_runtime" in service
    assert "import bot" not in service
    assert "from bot import" not in service


def test_bot_keeps_discord_registration_and_binds_voice_runtime_explicitly():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    assert "@vip_group.command(" in bot_source
    assert "async def vip_create_voice" in bot_source
    assert "@bot.event" in bot_source
    assert "async def on_voice_state_update" in bot_source
    assert "configure_vip_voice_runtime(" in bot_source
    assert "set_vip_voice_hidden_user_ids(HIDDEN_VIP_USER_IDS)" in bot_source
''',
    encoding="utf-8",
)

budget_path = ROOT / "tests" / "test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
bot_size = BOT.stat().st_size
service_size = SERVICE.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
bot_limit = round_up(bot_size)
service_limit = round_up(service_size)
budget = budget.replace(
    '    "bot.py": 273_000,\n',
    f'    "bot.py": {bot_limit:_},\n'
    f'    "services/vip_voice_runtime.py": {service_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"bot.py bytes={bot_size} ceiling={bot_limit}")
print(f"vip_voice_runtime.py bytes={service_size} ceiling={service_limit}")
