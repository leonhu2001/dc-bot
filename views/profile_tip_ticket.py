"""Private profile-tip ticket's persistent entry button."""
from __future__ import annotations

import discord

from views.worker_tips import WorkerTipAmountModal


class WorkerTipProfileStartView(discord.ui.View):
    def __init__(self, customer_id: int, target: dict):
        super().__init__(timeout=None)
        self.customer_id = int(customer_id)
        self.target = dict(target)
        button = discord.ui.Button(
            label="🍗 輸入雞腿金額",
            style=discord.ButtonStyle.success,
            custom_id=(
                f"worker_tip_profile_start:{self.customer_id}:"
                f"{self.target.get('staff_id')}"
            ),
        )
        button.callback = self.open_tip
        self.add_item(button)

    async def open_tip(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有開啟這張雞腿票口的老闆可以加雞腿。", ephemeral=True
            )
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到雞腿專用票口。", ephemeral=True
            )
            return
        parts = {
            entry.split("=", 1)[0]: entry.split("=", 1)[1]
            for entry in str(channel.topic or "").split(";") if "=" in entry
        }
        if (
            parts.get("tip_customer_id") != str(self.customer_id)
            or parts.get("tip_staff_id") != str(self.target.get("staff_id"))
        ):
            await interaction.response.send_message(
                "這不是有效的雞腿專用票口。", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            WorkerTipAmountModal(
                customer_id=self.customer_id,
                ticket_channel_id=channel.id,
                target=self.target,
                standalone=True,
            )
        )
