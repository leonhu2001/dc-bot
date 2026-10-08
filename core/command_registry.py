from __future__ import annotations

import re
from typing import Any

import discord
from discord import app_commands


# Canonical Discord chat-input command names. These are the names registered with
# Discord, not merely zh-TW localizations. Keeping the mapping centralized lets
# legacy internal callers (for example the staff management Panel) continue to
# resolve the old English paths while Discord itself only receives Chinese names.
CANONICAL_COMMAND_NAMES: dict[str, str] = {
    # top-level groups
    "order": "訂單",
    "vip": "貴賓",
    "member": "會員",
    "reward": "會員管理",
    "customer": "顧客管理",
    "stats": "營運",
    "audit": "系統",
    "setup": "設定",
    "lottery": "抽獎",
    "staff": "人員",

    # public / member commands
    "my_favorites": "我的收藏",
    "browse_staff_profiles": "瀏覽個人牆",
    "my_wallet_history": "我的錢包流水",
    "my_info": "我的會員資料",
    "points": "我的資料",

    # staff profile / repair tools
    "fix_acceptance_payment_panel": "補送付款面板",
    "staff_profile_panel": "建立個人牆面板",
    "refresh_staff_profile_panel": "更新個人牆面板",
    "reward_redeem_panel": "點數兌換面板",
    "set_customer_level": "設定會員等級",

    # order tools
    "order_search": "訂單查詢",
    "stored_orders": "存單查詢",
    "check_stored_orders": "檢查逾期存單",
    "delete_order": "刪除訂單",
    "fix_order_amount": "修正訂單金額",
    "fix_order_customer": "修正訂單顧客",
    "resend_dispatch": "重新派單",
    "delete_dispatch_panel": "刪除派單面板",

    # wallet
    "wallet_history": "錢包流水",
    "wallet_add": "錢包加值",
    "wallet_adjust": "錢包調整",
    "wallet_refund": "錢包退款",
    "wallet_refund_order": "訂單退款至錢包",

    # rewards / customer
    "customer_points": "會員資料",
    "adjust_points": "調整點數",
    "add_purchase": "補登消費",
    "import_purchases": "批量補登消費",
    "set_customer_rewards": "修正會員資料",
    "notes": "備註查詢",
    "add_note": "新增備註",
    "remove_note": "刪除備註",

    # stats / audit
    "today": "今日",
    "month": "本月",
    "top_customers": "消費排行",
    "check_vip_downgrades": "檢查會員降階",
    "data": "資料檢查",

    # setup
    "panel": "面板",
    "staff_panel": "客服管理面板",
    "topup_panel": "儲值面板",
    "complaint_panel": "客訴面板",
    "feedback_panel": "意見箱面板",
    "play_voice": "陪玩語音",
    "vip_voice": "貴賓語音",
    "public_voice": "公共語音",

    # VIP voice administration
    "hidden_add": "新增隱藏貴賓",
    "hidden_remove": "移除隱藏貴賓",
    "hidden_list": "隱藏貴賓名單",
    "create_voice": "建立貴賓語音",

    # lottery / sync
    "status": "查看狀態",
    "draw": "開獎",
    "sync_members": "同步人員",
}


_IDENTIFIER_TOKENS: dict[str, str] = {
    "my": "我的",
    "order": "訂單",
    "orders": "訂單",
    "stored": "存單",
    "search": "查詢",
    "check": "檢查",
    "delete": "刪除",
    "fix": "修正",
    "amount": "金額",
    "customer": "顧客",
    "customers": "顧客",
    "resend": "重送",
    "dispatch": "派單",
    "panel": "面板",
    "acceptance": "接單",
    "payment": "付款",
    "wallet": "錢包",
    "history": "流水",
    "refund": "退款",
    "add": "新增",
    "adjust": "調整",
    "reward": "會員",
    "redeem": "兌換",
    "member": "會員",
    "points": "點數",
    "purchase": "消費",
    "purchases": "消費",
    "import": "批量匯入",
    "set": "設定",
    "level": "等級",
    "info": "資料",
    "favorites": "收藏",
    "browse": "瀏覽",
    "staff": "人員",
    "profile": "個人牆",
    "profiles": "個人牆",
    "refresh": "更新",
    "notes": "備註",
    "note": "備註",
    "remove": "刪除",
    "stats": "營運",
    "today": "今日",
    "month": "本月",
    "top": "排行",
    "audit": "系統",
    "data": "資料",
    "setup": "設定",
    "topup": "儲值",
    "complaint": "客訴",
    "feedback": "意見",
    "play": "陪玩",
    "voice": "語音",
    "vip": "貴賓",
    "public": "公共",
    "lottery": "抽獎",
    "status": "狀態",
    "draw": "開獎",
    "sync": "同步",
    "members": "人員",
    "hidden": "隱藏貴賓",
    "create": "建立",
    "list": "名單",
}

_ASCII_COMMAND_CHARS = re.compile(r"[A-Za-z_]")
_INSTALLED = False
_ORIGINAL_TREE_SYNC: Any = None
_ORIGINAL_TREE_GET_COMMAND: Any = None
_ORIGINAL_GROUP_GET_COMMAND: Any = None


def canonical_command_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw

    explicit = CANONICAL_COMMAND_NAMES.get(raw)
    if explicit:
        return explicit

    # Already-canonical Chinese names pass through unchanged.
    if not _ASCII_COMMAND_CHARS.search(raw):
        return raw

    parts = [part for part in raw.lower().split("_") if part]
    if not parts:
        return raw

    translated: list[str] = []
    for part in parts:
        token = _IDENTIFIER_TOKENS.get(part)
        if token is None:
            return raw
        translated.append(token)

    result = "".join(translated)
    return result[:32] if result else raw


def _legacy_alias(name: str) -> str | None:
    target = canonical_command_name(name)
    return target if target and target != name else None


def _original_tree_get_command(
    tree: app_commands.CommandTree,
    name: str,
    *,
    guild: discord.abc.Snowflake | None = None,
    type: discord.AppCommandType = discord.AppCommandType.chat_input,
):
    return _ORIGINAL_TREE_GET_COMMAND(tree, name, guild=guild, type=type)


def _original_group_get_command(group: app_commands.Group, name: str):
    return _ORIGINAL_GROUP_GET_COMMAND(group, name)


def _canonicalize_group(group: app_commands.Group) -> None:
    for child in list(group.commands):
        if isinstance(child, app_commands.Group):
            _canonicalize_group(child)

        old_name = child.name
        new_name = canonical_command_name(old_name)
        if new_name == old_name:
            continue

        existing = _original_group_get_command(group, new_name)
        if existing is not None and existing is not child:
            raise RuntimeError(
                f"Slash 指令中文名稱衝突：{group.name} {old_name} -> {new_name}"
            )

        # discord.py Group.remove_command mutates the child mapping in-place and
        # intentionally does not return the removed command.
        group.remove_command(old_name)
        if _original_group_get_command(group, old_name) is not None:
            raise RuntimeError(f"無法從群組移除 Slash 指令：{group.name} {old_name}")

        child.name = new_name
        group.add_command(child)


def _canonicalize_scope(
    tree: app_commands.CommandTree,
    *,
    guild: discord.abc.Snowflake | None,
) -> None:
    for command in list(tree.get_commands(guild=guild)):
        if not isinstance(command, (app_commands.Command, app_commands.Group)):
            continue

        if isinstance(command, app_commands.Group):
            _canonicalize_group(command)

        old_name = command.name
        new_name = canonical_command_name(old_name)
        if new_name == old_name:
            continue

        existing = _original_tree_get_command(tree, new_name, guild=guild)
        if existing is not None and existing is not command:
            scope = f"guild={getattr(guild, 'id', None)}" if guild else "global"
            raise RuntimeError(
                f"Slash 指令中文名稱衝突：{scope} {old_name} -> {new_name}"
            )

        # These are chat-input Command/Group objects. Context-menu commands are
        # deliberately skipped above, so the default type is the correct one.
        removed = tree.remove_command(old_name, guild=guild)
        if removed is None:
            raise RuntimeError(f"無法從 CommandTree 移除 Slash 指令：{old_name}")

        command.name = new_name
        tree.add_command(command, guild=guild)


def canonicalize_tree(
    tree: app_commands.CommandTree,
    *,
    guild: discord.abc.Snowflake | None = None,
) -> None:
    # The bot primarily syncs one guild, but global syncs are supported as well.
    _canonicalize_scope(tree, guild=guild)


def _tree_get_command_with_legacy_alias(
    self: app_commands.CommandTree,
    name: str,
    *,
    guild: discord.abc.Snowflake | None = None,
    type: discord.AppCommandType = discord.AppCommandType.chat_input,
):
    command = _ORIGINAL_TREE_GET_COMMAND(self, name, guild=guild, type=type)
    if command is not None:
        return command

    alias = _legacy_alias(name)
    if alias is None:
        return None
    return _ORIGINAL_TREE_GET_COMMAND(self, alias, guild=guild, type=type)


def _group_get_command_with_legacy_alias(self: app_commands.Group, name: str):
    command = _ORIGINAL_GROUP_GET_COMMAND(self, name)
    if command is not None:
        return command

    alias = _legacy_alias(name)
    if alias is None:
        return None
    return _ORIGINAL_GROUP_GET_COMMAND(self, alias)


async def _clear_stale_remote_global_commands(
    tree: app_commands.CommandTree,
) -> None:
    if getattr(tree, "_stale_global_cleanup_checked", False):
        return

    tree._stale_global_cleanup_checked = True

    try:
        remote_global_commands = await tree.fetch_commands()
    except discord.HTTPException as exc:
        print(
            "[commands] unable to inspect global commands; "
            f"guild sync will continue: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return

    if not remote_global_commands:
        return

    local_global_commands = list(tree.get_commands())

    tree.clear_commands(guild=None)
    try:
        await _ORIGINAL_TREE_SYNC(tree)
    finally:
        for command in local_global_commands:
            tree.add_command(command)

    print(
        "[commands] cleared stale global commands: "
        f"{len(remote_global_commands)}",
        flush=True,
    )


async def _sync_with_canonical_names(self: app_commands.CommandTree, *args, **kwargs):
    guild = kwargs.get("guild")

    # This bot intentionally publishes commands to its one guild. Historical
    # deployments also registered global English commands; a guild-only sync does
    # not delete those, so Discord can show both the new Chinese guild commands and
    # the old English global commands. Before the first guild sync, remove any
    # remote globals while preserving the local command objects used by the bot.
    if guild is not None:
        await _clear_stale_remote_global_commands(self)

    canonicalize_tree(self, guild=guild)
    return await _ORIGINAL_TREE_SYNC(self, *args, **kwargs)


def install_canonical_command_registry() -> None:
    """Install the canonical-name boundary before any Discord command sync.

    The source callbacks keep their existing Python function names and legacy paths.
    At the CommandTree boundary, every chat-input command/group is registered under
    its canonical Chinese name. Legacy English lookups remain valid so existing
    Panel callbacks do not break during the migration.
    """

    global _INSTALLED
    global _ORIGINAL_TREE_SYNC
    global _ORIGINAL_TREE_GET_COMMAND
    global _ORIGINAL_GROUP_GET_COMMAND

    if _INSTALLED:
        return

    _ORIGINAL_TREE_SYNC = app_commands.CommandTree.sync
    _ORIGINAL_TREE_GET_COMMAND = app_commands.CommandTree.get_command
    _ORIGINAL_GROUP_GET_COMMAND = app_commands.Group.get_command

    app_commands.CommandTree.sync = _sync_with_canonical_names
    app_commands.CommandTree.get_command = _tree_get_command_with_legacy_alias
    app_commands.Group.get_command = _group_get_command_with_legacy_alias

    _INSTALLED = True
