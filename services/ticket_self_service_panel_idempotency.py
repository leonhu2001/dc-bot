"""Reuse the initial order panel when staff reopens an existing ticket form."""
from __future__ import annotations

from collections.abc import Callable

import discord


async def ensure_ticket_self_service_panel(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    selections: dict,
    bot_user_id: int | None,
    view_type: type,
    panel_embed_builder: Callable,
    remember_data: Callable,
    fallback_embed: discord.Embed,
) -> discord.Message:
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("下單票口不存在")

    draft = selections.setdefault(channel.id, {})
    existing_panel = None
    saved_id = draft.get("self_service_panel_message_id")
    if saved_id:
        try:
            existing_panel = await channel.fetch_message(int(saved_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            pass

    if existing_panel is None:
        try:
            async for message in channel.history(limit=100):
                if bot_user_id is not None and message.author.id != bot_user_id:
                    continue
                if any(
                    str(getattr(component, "custom_id", "") or "").startswith("self_service_order_")
                    for row in (message.components or [])
                    for component in (getattr(row, "children", []) or [])
                ):
                    existing_panel = message
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

    view = view_type(
        customer_id=customer_id,
        channel_id=channel.id,
        selected_category=draft.get("category") if draft.get("quick_order_v2") else None,
    )

    if existing_panel is not None:
        await existing_panel.edit(
            embed=panel_embed_builder(customer_id, draft, interaction.guild),
            view=view,
        )
        result = existing_panel
    else:
        result = await channel.send(
            embed=fallback_embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )

    draft["self_service_panel_message_id"] = result.id
    remember_data(channel.id, draft)
    return result
