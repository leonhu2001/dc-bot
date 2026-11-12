"""Prevent duplicate self-service panels inside an existing order ticket.

A quick-order ticket already contains the active selector message. Staff using
the legacy order-control '派單' action must not send a second copy. Both
parallel confirm callbacks and later repeats serialize per channel and reuse
the original message.
"""
from __future__ import annotations

import asyncio
import discord

_PANEL_LOCKS: dict[int, asyncio.Lock] = {}


def _is_self_service_panel(message, *, bot_id: int | None) -> bool:
    if bot_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_id:
        return False
    embeds = getattr(message, "embeds", ()) or ()
    title = str(getattr(embeds[0], "title", "") or "") if embeds else ""
    if title not in ("自助下單", "🛒 自助下單") and not title.startswith("快速下單｜"):
        return False
    components = getattr(message, "components", ()) or ()
    for row in components:
        for child in getattr(row, "children", ()) or ():
            if str(getattr(child, "custom_id", "") or "").startswith("self_service_order_"):
                return True
    # Early legacy panels also use the same title but may lack components.
    return title in ("自助下單", "🛒 自助下單")


async def ensure_single_self_service_panel(
    channel: discord.TextChannel,
    *,
    customer_id: int,
    embed: discord.Embed,
    view_factory,
) -> tuple[discord.Message, bool]:
    lock = _PANEL_LOCKS.setdefault(int(channel.id), asyncio.Lock())
    async with lock:
        bot_id = getattr(getattr(channel.guild, "me", None), "id", None)
        async for message in channel.history(limit=80):
            if _is_self_service_panel(message, bot_id=bot_id):
                return message, False
        created = await channel.send(
            embed=embed,
            view=view_factory(customer_id=int(customer_id),channel_id=int(channel.id)),
            allowed_mentions=discord.AllowedMentions(users=False,roles=False,everyone=False),
        )
        return created, True


__all__=["ensure_single_self_service_panel","_is_self_service_panel"]
