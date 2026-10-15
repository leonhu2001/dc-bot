from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord


def is_order_already_closed(order_data: dict) -> bool:
    status = str(order_data.get("status") or "").strip().lower()
    return bool(order_data.get("closed")) or status in {"closed", "completed", "done"}


def _message_has_review_panel(message: discord.Message) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == "review_leave_button":
                return True
    return False


async def ensure_post_close_panel(
    *,
    order_channel: discord.TextChannel,
    order_data: dict,
    customer_id: int,
    order_content: str | None,
    content: str,
    build_embed: Callable[[int, int], discord.Embed],
    build_view: Callable[..., discord.ui.View],
    remember_order: Callable[[int, dict], Any],
) -> tuple[discord.Message, bool]:
    """Return one public post-close panel, creating it only when necessary.

    This is deliberately independent from the close transaction. Retrying a close
    after the order is already closed may repair the UI, but must not repeat
    receipt creation, rewards, payout, or WebOrder state transitions.
    """
    panel_message = None
    stored_message_id = order_data.get("post_close_panel_message_id")

    if stored_message_id is not None:
        try:
            panel_message = await order_channel.fetch_message(int(stored_message_id))
        except (TypeError, ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            panel_message = None

    if panel_message is None:
        try:
            async for message in order_channel.history(limit=100):
                if _message_has_review_panel(message):
                    panel_message = message
                    break
        except (discord.Forbidden, discord.HTTPException):
            panel_message = None

    embed = build_embed(order_channel.id, customer_id)
    view = build_view(customer_id=customer_id, order_content=order_content)
    allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)

    if panel_message is not None:
        try:
            await panel_message.edit(
                content=content,
                embed=embed,
                view=view,
                allowed_mentions=allowed_mentions,
            )
            order_data["post_close_panel_message_id"] = panel_message.id
            remember_order(order_channel.id, order_data)
            return panel_message, False
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            panel_message = None

    panel_message = await order_channel.send(
        content=content,
        embed=embed,
        view=view,
        allowed_mentions=allowed_mentions,
    )
    order_data["post_close_panel_message_id"] = panel_message.id
    remember_order(order_channel.id, order_data)
    return panel_message, True
