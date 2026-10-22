from __future__ import annotations

import re

import discord
from discord.ext import commands

from core.config import config_int
from services.ticket_identity import build_ticket_channel_name


CUSTOMER_CATEGORY_ID = config_int("CUSTOMER_CATEGORY_ID", 1483895536938651809)
_SIMPLIFIED_NAME_RE = re.compile(r"^[🟢🟡🟠⚫🔴⚪][・┃]客服中心$")


def _topic_customer_id(channel: discord.TextChannel) -> int | None:
    for part in str(channel.topic or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() != "order_customer_id":
            continue
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _legacy_prefix(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "stored":
        return "存單"
    if normalized == "closed":
        return "已結單"
    if normalized in {"cancelled", "canceled"}:
        return "已取消"
    return "下單"


async def restore_unintentionally_simplified_order_ticket_names(
    bot: commands.Bot,
) -> None:
    """Undo only the temporary status-emoji-only ticket naming rollout."""
    await bot.wait_until_ready()

    category = bot.get_channel(CUSTOMER_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        try:
            fetched = await bot.fetch_channel(CUSTOMER_CATEGORY_ID)
            category = fetched if isinstance(fetched, discord.CategoryChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            category = None

    if not isinstance(category, discord.CategoryChannel):
        return

    try:
        from services import self_service_ui_runtime as ui
        selections = ui.SELF_SERVICE_ORDER_SELECTIONS
    except Exception:
        selections = {}

    restored = 0
    for channel in list(category.text_channels):
        if not _SIMPLIFIED_NAME_RE.fullmatch(str(channel.name or "")):
            continue

        customer_id = _topic_customer_id(channel)
        if customer_id is None:
            continue

        data = selections.get(channel.id, {}) if isinstance(selections, dict) else {}
        status = str(data.get("status") or "") if isinstance(data, dict) else ""
        prefix = _legacy_prefix(status)

        member = channel.guild.get_member(customer_id)
        if member is None:
            try:
                member = await channel.guild.fetch_member(customer_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        display_name = None
        if member is None and isinstance(data, dict):
            display_name = str(data.get("customer_display_name") or "").strip() or None

        new_name = build_ticket_channel_name(
            prefix,
            member,
            display_name=display_name or str(customer_id),
        )
        if channel.name == new_name:
            continue

        try:
            await channel.edit(
                name=new_name,
                reason="Restore legacy order ticket naming after mistaken rollout",
            )
            restored += 1
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[order-ticket-name-restore] rename failed channel={channel.id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if restored:
        print(
            f"[order-ticket-name-restore] restored {restored} order ticket channel(s)",
            flush=True,
        )


def install_order_ticket_name_restore(bot: commands.Bot) -> None:
    if getattr(bot, "_order_ticket_name_restore_started", False):
        return
    bot._order_ticket_name_restore_started = True
    bot.loop.create_task(restore_unintentionally_simplified_order_ticket_names(bot))


__all__ = [
    "install_order_ticket_name_restore",
    "restore_unintentionally_simplified_order_ticket_names",
]
