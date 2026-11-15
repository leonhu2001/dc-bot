"""Reuse the initial order panel when staff reopens an existing ticket form."""
from __future__ import annotations

from collections.abc import Callable
import asyncio
import logging

import discord


_LOG = logging.getLogger(__name__)
_REISSUE_LOCKS: dict[int, asyncio.Lock] = {}


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
    reissue_full_selection: bool = False,
) -> discord.Message:
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("下單票口不存在")

    if reissue_full_selection:
        # This path is the staff-confirmed "填寫自助下單" action, not the
        # ordinary create/restore path. Always put a brand-new, complete form
        # at the BOTTOM of the ticket. Editing an old buried message made the
        # confirmation appear to do nothing.
        lock = _REISSUE_LOCKS.setdefault(int(channel.id), asyncio.Lock())
        async with lock:
            old_draft = dict(selections.get(channel.id) or {})
            if any(
                old_draft.get(key)
                for key in (
                    "dispatch_message_id",
                    "web_order_id",
                    "payment_message_id",
                    "website_finance_settled",
                )
            ):
                raise ValueError(
                    "這張票口已有派單或付款紀錄，不能清空重選。"
                    "請由客服依正常取消／重開票口流程處理，避免重複派單或扣款。"
                )

            # Retain only ticket identity, not old product selections, prices,
            # coupons or payment preferences. Reorder provenance is harmless
            # and must not be lost on a copied ticket.
            fresh = {"customer_id": int(customer_id)}
            for key, value in old_draft.items():
                if str(key).startswith("reorder_source_"):
                    fresh[key] = value

            # Disable the Quick Order ticket's short-form layout: its runtime
            # view hides category and group. This panel must display all four
            # selectors regardless of how the ticket was originally opened.
            # Create the view against the fresh in-memory draft before send;
            # restore the old draft if the Discord API rejects the message.
            previous = selections.get(channel.id)
            selections[channel.id] = fresh
            try:
                view = view_type(
                    customer_id=customer_id,
                    channel_id=channel.id,
                    selected_category=None,
                )
                embed = panel_embed_builder(customer_id, fresh, interaction.guild)
                result = await channel.send(
                    content=(
                        f"<@{customer_id}> 已重新開啟完整自助下單，"
                        "請從「訂單類別」開始重新選擇所有選項。"
                    ),
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False,
                    ),
                )
            except Exception:
                if previous is None:
                    selections.pop(channel.id, None)
                else:
                    selections[channel.id] = previous
                raise

            fresh["self_service_panel_message_id"] = result.id
            remember_data(channel.id, fresh)

            # Retire the previous interactive form, so only the new last panel
            # is actionable. Do not delete anything or fail a successful send
            # merely because an old message cannot be edited anymore.
            old_id = old_draft.get("self_service_panel_message_id")
            if old_id and str(old_id) != str(result.id):
                try:
                    old_message = await channel.fetch_message(int(old_id))
                    await old_message.edit(view=None)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError, ValueError):
                    _LOG.warning(
                        "reissued self-service panel but could not retire old controls ticket=%s old=%s",
                        channel.id, old_id,
                    )
            return result

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
