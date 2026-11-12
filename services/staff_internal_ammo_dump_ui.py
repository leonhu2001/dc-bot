from __future__ import annotations

import discord

from core.permissions import is_customer_staff
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RULE_KEY, AMMO_DUMP_RUSH_RULE_KEY, INTERNAL_PRIORITY_FEE,
    is_internal_ammo_dump_rule,
)


class InternalAmmoNamedSelect(discord.ui.Select):
    """Send-order-only choice: selecting an option opens the existing note modal."""

    def __init__(self, *, customer_id: int, channel_id: int, panel_message_id: int | None, priority: bool = False):
        self.priority = bool(priority)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        super().__init__(
            custom_id="staff_internal_ammo_named_select",
            placeholder="送單時選擇：有掛名／無掛名",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"有掛名｜顧客 {2650 + (INTERNAL_PRIORITY_FEE if self.priority else 0):,}T",
                    value="named",
                    description="加急全給打手；店抽 0T" if self.priority else "代肝 2,650T；店家差額 0T",
                ),
                discord.SelectOption(
                    label=f"無掛名｜顧客 {3000 + (INTERNAL_PRIORITY_FEE if self.priority else 0):,}T",
                    value="unnamed",
                    description="加急全給打手；客服 88T；店家 262T" if self.priority else "代肝 2,650T；客服 88T；店家 262T",
                ),
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以選擇掛名狀態並送出訂單。", ephemeral=True)
            return
        if interaction.channel is None or int(interaction.channel.id) != self.channel_id:
            await interaction.response.send_message("請在原本的訂單票口操作。", ephemeral=True)
            return

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id)
        if not isinstance(data, dict) or not is_internal_ammo_dump_rule(data.get("order_rule_key")):
            await interaction.response.send_message("訂單商品已變更，請重新按「送出等待接單」。", ephemeral=True)
            return

        if data.get("dispatch_message_id") or str(data.get("status") or "").strip().lower() in {
            "waiting_acceptance", "accepted_pending_pay", "active", "stored", "completed", "cancelled"
        }:
            await interaction.response.send_message("這張訂單已送出，不能變更掛名狀態。", ephemeral=True)
            return

        named = self.values[0] == "named"
        # Keep the choice on the modal until the CS actually submits its note.
        # Cancelling the modal must not silently save a price selection.
        await interaction.response.send_modal(
            ui.SelfServiceSubmitNoteModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=self.panel_message_id,
                ammo_named_selection=named,
            )
        )


class InternalAmmoNamedView(discord.ui.View):
    def __init__(self, *, customer_id: int, channel_id: int, panel_message_id: int | None, priority: bool = False):
        super().__init__(timeout=300)
        self.add_item(
            InternalAmmoNamedSelect(
                customer_id=customer_id,
                channel_id=channel_id,
                panel_message_id=panel_message_id,
                priority=priority,
            )
        )


__all__ = ["InternalAmmoNamedView", "InternalAmmoNamedSelect"]
