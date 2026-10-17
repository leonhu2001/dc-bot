from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import discord


_REPOSITION_LOCKS: dict[int, asyncio.Lock] = {}


def _is_active_order(order_data: object) -> bool:
    return (
        isinstance(order_data, dict)
        and str(order_data.get("status") or "").strip().lower() == "active"
    )


async def _reposition_panel(
    channel: discord.TextChannel,
    *,
    expected_panel_message_id: int,
    order_selections: dict[int, dict[str, Any]],
    to_int: Callable[[Any], int | None],
    operation_view_factory: Callable[[], discord.ui.View],
    remember_order: Callable[[int, dict[str, Any]], None],
    save_data: Callable[[], None],
) -> None:
    lock = _REPOSITION_LOCKS.setdefault(channel.id, asyncio.Lock())
    async with lock:
        order_data = order_selections.get(channel.id)
        if not _is_active_order(order_data):
            return

        panel_message_id = to_int(order_data.get("operation_panel_message_id"))
        if panel_message_id is None or panel_message_id != expected_panel_message_id:
            return

        try:
            old_panel = await channel.fetch_message(panel_message_id)
            await old_panel.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException):
            return

        order_data = order_selections.get(channel.id)
        if not _is_active_order(order_data):
            return
        if to_int(order_data.get("operation_panel_message_id")) != panel_message_id:
            return

        operation_embed = discord.Embed(
            title="訂單操作",
            description="請客服從下拉式清單選擇後，按下確認。",
            color=discord.Color.green(),
        )
        try:
            new_panel = await channel.send(
                embed=operation_embed,
                view=operation_view_factory(),
            )
        except (discord.Forbidden, discord.HTTPException):
            return

        order_data["operation_panel_message_id"] = new_panel.id
        order_selections[channel.id] = order_data
        remember_order(channel.id, order_data)
        save_data()


async def handle_order_operation_panel_interaction(
    interaction: discord.Interaction,
    *,
    order_selections: dict[int, dict[str, Any]],
    is_staff: Callable[[discord.Member], bool],
    to_int: Callable[[Any], int | None],
    operation_view_factory: Callable[[], discord.ui.View],
    remember_order: Callable[[int, dict[str, Any]], None],
    save_data: Callable[[], None],
) -> None:
    if interaction.type is not discord.InteractionType.component:
        return
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        return
    if interaction.message is None or interaction.message.flags.ephemeral:
        return

    interaction_data = interaction.data if isinstance(interaction.data, dict) else {}
    custom_id = str(interaction_data.get("custom_id") or "")
    if not custom_id or custom_id in {
        "staff_order_operation_select",
        "staff_order_operation_confirm",
    }:
        return

    order_data = order_selections.get(interaction.channel.id)
    if not _is_active_order(order_data):
        return

    panel_message_id = to_int(order_data.get("operation_panel_message_id"))
    if panel_message_id is None:
        return

    # Give the component callback first chance to change the order state.
    await asyncio.sleep(0.8)
    await _reposition_panel(
        interaction.channel,
        expected_panel_message_id=panel_message_id,
        order_selections=order_selections,
        to_int=to_int,
        operation_view_factory=operation_view_factory,
        remember_order=remember_order,
        save_data=save_data,
    )
