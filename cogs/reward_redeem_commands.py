from __future__ import annotations

import discord
from discord.ext import commands

from services.point_benefit_catalog import (
    POINT_REDEEM_ITEMS,
    POINT_REDEEM_ITEMS_BY_KEY,
)


_RETIRED_MESSAGE = (
    "這個舊版點數兌換面板已停用。\n"
    "點數福利已整合到自助下單流程，請直接從自助下單的「點數／會員福利」選擇使用。"
)


class LegacyRewardRedeemSelect(discord.ui.Select):
    """Compatibility handler for already-posted legacy redemption panels."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=str(item.get("name") or item.get("key") or "點數福利")[:100],
                value=str(item.get("key") or "retired")[:100],
            )
            for item in POINT_REDEEM_ITEMS[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="點數福利已移至自助下單", value="retired")]

        super().__init__(
            placeholder="點數福利已移至自助下單",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="reward_redeem_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(_RETIRED_MESSAGE, ephemeral=True)


class RewardRedeemView(discord.ui.View):
    """Keep old message custom IDs alive without allowing legacy direct redemption."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LegacyRewardRedeemSelect())

    @discord.ui.button(
        label="兌換",
        style=discord.ButtonStyle.secondary,
        custom_id="reward_redeem_confirm_button",
    )
    async def redeem_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        await interaction.response.send_message(_RETIRED_MESSAGE, ephemeral=True)


async def setup(bot: commands.Bot):
    # The standalone /reward_redeem_panel command is intentionally retired.
    # bot.py still imports the canonical catalog from this compatibility module
    # and registers RewardRedeemView so old posted panels fail closed with a
    # migration hint instead of silently timing out or using stale point prices.
    del bot
