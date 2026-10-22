from __future__ import annotations

import discord
from discord.ext import commands

from core.config import config_int
from services.ticket_identity import order_ticket_channel_name_for_status


CUSTOMER_CATEGORY_ID = config_int("CUSTOMER_CATEGORY_ID", 1483895536938651809)


def _fallback_status_from_name(name: str) -> str:
    text = str(name or "").lower()
    if any(token in text for token in ("取消", "cancel")):
        return "cancelled"
    if any(token in text for token in ("結單", "closed")):
        return "closed"
    if any(token in text for token in ("存單", "stored", "暫存")):
        return "stored"
    if any(token in text for token in ("待付款", "等待", "pending")):
        return "waiting_acceptance"
    return "active"


async def normalize_existing_order_ticket_names(bot: commands.Bot) -> None:
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

    changed = 0
    for channel in list(category.text_channels):
        if "order_customer_id=" not in str(channel.topic or ""):
            continue

        data = selections.get(channel.id, {}) if isinstance(selections, dict) else {}
        status = str(data.get("status") or "").strip().lower() if isinstance(data, dict) else ""
        if not status:
            status = _fallback_status_from_name(channel.name)

        new_name = order_ticket_channel_name_for_status(status)
        if channel.name == new_name:
            continue

        try:
            await channel.edit(
                name=new_name,
                reason="Normalize order ticket name to status emoji + 客服中心",
            )
            changed += 1
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[order-ticket-name] rename failed channel={channel.id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if changed:
        print(
            f"[order-ticket-name] normalized {changed} order ticket channel(s)",
            flush=True,
        )


def install_order_ticket_name_sync(bot: commands.Bot) -> None:
    if getattr(bot, "_order_ticket_name_sync_started", False):
        return
    bot._order_ticket_name_sync_started = True
    bot.loop.create_task(normalize_existing_order_ticket_names(bot))


__all__ = ["install_order_ticket_name_sync", "normalize_existing_order_ticket_names"]
