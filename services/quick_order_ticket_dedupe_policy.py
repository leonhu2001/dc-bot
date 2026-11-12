"""Idempotent self-service panel creation inside an existing order ticket.

The quick-order entry flow already creates the selector at ticket creation.
The legacy customer-service 'fill self service' action must reuse that selector
instead of posting a second copy in the same ticket.
"""
from __future__ import annotations

import asyncio

_PANEL_CREATE_LOCK = asyncio.Lock()
_PANEL_SELECT_IDS = frozenset({
    "self_service_order_category_select",
    "self_service_order_item_select",
    "self_service_order_detail_select",
    "self_service_order_go_payment_button",
})


def message_is_self_service_panel(message, bot_user_id: int | None = None) -> bool:
    if bot_user_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_user_id:
        return False
    for row in getattr(message, "components", ()) or ():
        for child in getattr(row, "children", ()) or ():
            if getattr(child, "custom_id", None) in _PANEL_SELECT_IDS:
                return True
    # Fall back for older bot versions or panels whose original view has
    # expired but whose embed is still present in the ticket.
    for embed in getattr(message, "embeds", ()) or ():
        title = str(getattr(embed, "title", "") or "")
        if title == "自助下單" or title.startswith("🛒 "):
            return True
    return False


async def has_self_service_panel(channel, *, limit: int = 45) -> bool:
    bot_id = getattr(getattr(getattr(channel, "guild", None), "me", None), "id", None)
    async for message in channel.history(limit=limit, oldest_first=False):
        if message_is_self_service_panel(message, bot_id):
            return True
    return False


async def send_self_service_panel_once(channel, *, embed, view, allowed_mentions) -> bool:
    # One lock covers concurrent '確認' events even if they use different
    # discord.ui.View objects attached to the same existing ticket.
    async with _PANEL_CREATE_LOCK:
        if await has_self_service_panel(channel):
            return False
        await channel.send(embed=embed, view=view, allowed_mentions=allowed_mentions)
        return True


async def send_legacy_control_panel_once(
    interaction, *, embed, view, allowed_mentions,
) -> bool:
    """Reuse quick-order selector rather than sending a second one."""
    created = await send_self_service_panel_once(
        interaction.channel, embed=embed, view=view,
        allowed_mentions=allowed_mentions,
    )
    if not created:
        await interaction.followup.send(
            "這個下單票口已經有自助下單面板，請使用原本的面板，不會重複發送。",
            ephemeral=True,
        )
    return created


__all__ = [
    "message_is_self_service_panel", "has_self_service_panel",
    "send_self_service_panel_once", "send_legacy_control_panel_once",
]
