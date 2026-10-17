from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import discord

from core.database import remember_order_data


_REPOSITION_LOCKS: dict[int, asyncio.Lock] = {}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _order_status(order_data: object) -> str:
    if not isinstance(order_data, dict):
        return ""
    return str(order_data.get("status") or "").strip().lower()


def _is_active_order(order_data: object) -> bool:
    return _order_status(order_data) == "active"


def _is_stored_order(order_data: object) -> bool:
    return _order_status(order_data) == "stored"


async def validate_staff_order_operation_interaction(
    interaction: discord.Interaction,
    is_staff: Callable[[discord.Member], bool],
) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return False
    if not is_staff(interaction.user):
        await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
        return False
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
        return False
    return True


async def _reposition_panel(
    channel: discord.TextChannel,
    *,
    expected_panel_message_id: int,
    order_selections: dict[int, dict[str, Any]],
    operation_view_factory: Callable[[], discord.ui.View],
) -> None:
    lock = _REPOSITION_LOCKS.setdefault(channel.id, asyncio.Lock())
    async with lock:
        order_data = order_selections.get(channel.id)
        if not _is_active_order(order_data):
            return

        panel_message_id = _to_int(order_data.get("operation_panel_message_id"))
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
        if _to_int(order_data.get("operation_panel_message_id")) != panel_message_id:
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
        remember_order_data(channel.id, order_data)


async def handle_order_operation_panel_interaction(
    interaction: discord.Interaction,
    *,
    order_selections: dict[int, dict[str, Any]],
    is_staff: Callable[[discord.Member], bool],
    operation_view_factory: Callable[[], discord.ui.View],
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
    if not custom_id or custom_id == "staff_order_operation_select":
        return

    order_data = order_selections.get(interaction.channel.id)

    # The operation panel confirm button normally does not reposition itself.
    # Resume is the exception: the interaction starts while the order is stored,
    # then the callback switches it back to active. Waiting here lets the callback
    # finish first, after which _reposition_panel can safely move the panel down.
    if custom_id == "staff_order_operation_confirm":
        if not _is_stored_order(order_data):
            return
    elif not _is_active_order(order_data):
        return

    panel_message_id = _to_int(order_data.get("operation_panel_message_id"))
    if panel_message_id is None:
        return

    # Give the component callback first chance to change the order state.
    await asyncio.sleep(0.8)
    await _reposition_panel(
        interaction.channel,
        expected_panel_message_id=panel_message_id,
        order_selections=order_selections,
        operation_view_factory=operation_view_factory,
    )


def register_order_operation_panel_listener(
    bot: discord.Client,
    order_selections: dict[int, dict[str, Any]],
    is_staff: Callable[[discord.Member], bool],
    operation_view_factory: Callable[[], discord.ui.View],
) -> None:
    async def _listener(interaction: discord.Interaction) -> None:
        await handle_order_operation_panel_interaction(
            interaction,
            order_selections=order_selections,
            is_staff=is_staff,
            operation_view_factory=operation_view_factory,
        )

    bot.add_listener(_listener, "on_interaction")
