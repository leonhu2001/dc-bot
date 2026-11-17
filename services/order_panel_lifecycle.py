"""Order-operation + ordinary timer panel lifecycle, shared by ticket entrypoints.

Keep panel sequencing out of bot.py and the legacy order runtime.  The
existing operation-panel helper remains authoritative for posting the order
controls; it then moves the hourly clock as a separate, display-only panel.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping

import discord


async def reposition_after_status_transition(
    channel: discord.TextChannel,
    original_panel_id: object,
    expected_status: str,
    order_selections: Mapping[int, dict],
    view_factory: Callable[[], discord.ui.View] | None,
) -> None:
    """Idempotent across the explicit caller and the old interaction listener."""
    if not original_panel_id or view_factory is None:
        return
    current = order_selections.get(channel.id, {})
    if str(current.get("status") or "").lower() != expected_status:
        return
    try:
        from services.order_operation_panel_runtime import _reposition_panel

        await _reposition_panel(
            channel,
            expected_panel_message_id=int(original_panel_id),
            expected_status=expected_status,
            order_selections=order_selections,
            operation_view_factory=view_factory,
        )
    except Exception as exc:
        print(
            f"[order-operation] {expected_status} panel reposition failed "
            f"channel={channel.id}: {type(exc).__name__}: {exc}",
            flush=True,
        )


async def follow_restored_order_panel(
    channel: discord.TextChannel,
    original_panel_id: object,
    order_selections: Mapping[int, dict],
    view_factory: Callable[[], discord.ui.View],
) -> None:
    await reposition_after_status_transition(
        channel, original_panel_id, "active", order_selections, view_factory,
    )


async def finish_stored_order_modal(
    interaction: discord.Interaction,
    original_panel_id: object,
    order_selections: Mapping[int, dict],
    *,
    reason: str,
    expected_time: str,
    note: str,
) -> None:
    """Publish storage confirmation first, then move both panels to the bottom."""
    channel = interaction.channel
    await channel.send(
        f"此訂單已由 {interaction.user.mention} 存單。\n\n"
        f"存單原因：{reason}\n"
        f"預計恢復：{expected_time or '未填寫'}\n"
        f"備註：{note or '無'}",
        allowed_mentions=discord.AllowedMentions(
            users=True, roles=False, everyone=False,
        ),
    )
    await reposition_after_status_transition(
        channel, original_panel_id, "stored", order_selections,
        getattr(interaction.client, "_order_operation_panel_view_factory", None),
    )
    await interaction.followup.send(
        "已存單，派單頻道接單面板已鎖定。", ephemeral=True,
    )
