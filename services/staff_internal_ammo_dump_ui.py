from __future__ import annotations

import discord

from core.permissions import is_customer_staff
from services.staff_internal_ammo_dump_policy import AMMO_DUMP_RULE_KEY


class InternalAmmoNamedSelect(discord.ui.Select):
    """Send-order-only choice: selecting an option opens the existing note modal."""

    def __init__(self, *, customer_id: int, channel_id: int, panel_message_id: int | None):
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
                    label="有掛名｜顧客 2,650T",
                    value="named",
                    description="代肝 2,650T；店家差額 0T",
                ),
                discord.SelectOption(
                    label="無掛名｜顧客 3,000T",
                    value="unnamed",
                    description="代肝 2,650T；店家收入 350T",
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
        if not isinstance(data, dict) or str(data.get("order_rule_key") or "") != AMMO_DUMP_RULE_KEY:
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
    def __init__(self, *, customer_id: int, channel_id: int, panel_message_id: int | None):
        super().__init__(timeout=300)
        self.add_item(
            InternalAmmoNamedSelect(
                customer_id=customer_id,
                channel_id=channel_id,
                panel_message_id=panel_message_id,
            )
        )


__all__ = ["InternalAmmoNamedView", "InternalAmmoNamedSelect"]
