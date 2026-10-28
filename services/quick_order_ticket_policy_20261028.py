from __future__ import annotations

import discord


_INSTALLED = False


class QuickOrderNoticeConfirmView(discord.ui.View):
    """Explicit order-notice acknowledgement before a quick-order ticket opens."""

    def __init__(
        self,
        *,
        customer_id: int,
        category: str,
        item_group: str,
        source_channel_id: int,
        quick_module,
    ):
        super().__init__(timeout=180)
        self.customer_id = int(customer_id)
        self.category = str(category)
        self.item_group = str(item_group)
        self.source_channel_id = int(source_channel_id)
        self.quick_module = quick_module
        self.opening = False

    @discord.ui.button(
        label="已閱讀下單須知，建立票口",
        emoji="✅",
        style=discord.ButtonStyle.success,
    )
    async def read_and_open(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return

        if self.opening:
            await interaction.response.send_message(
                "票口正在建立，請勿重複點擊。",
                ephemeral=True,
            )
            return

        self.opening = True
        for child in self.children:
            child.disabled = True

        # A component interaction must be acknowledged before the ticket creator
        # performs category/channel work. Keep this acknowledgement ephemeral and
        # leave quick_order_v2's original locked-service ticket UI untouched.
        await interaction.response.edit_message(view=self)
        try:
            await self.quick_module._create_ticket(
                interaction,
                category=self.category,
                item_group=self.item_group,
                source_channel_id=self.source_channel_id,
            )
            self.stop()
        except Exception:
            self.opening = False
            for child in self.children:
                child.disabled = False
            raise

    @discord.ui.button(
        label="尚未閱讀",
        emoji="📖",
        style=discord.ButtonStyle.secondary,
    )
    async def not_read(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "請先閱讀店內下單須知；確認看完後，再按「已閱讀下單須知，建立票口」。",
            ephemeral=True,
        )


async def _send_notice_confirmation(
    interaction: discord.Interaction,
    *,
    category: str,
    item_group: str,
    source_channel_id: int,
    quick_module,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    timer = category == quick_module.VIP_TIMER_CATEGORY
    category_label = (
        quick_module.VIP_TIMER_CATEGORY_LABEL
        if timer
        else quick_module.ORDER_CATEGORY_LABELS.get(category, category)
    )

    embed = discord.Embed(
        title="📖 下單須知確認",
        description=(
            f"**遊戲／類型：** {category_label}\n"
            f"**{'起始遊戲' if timer else '服務'}：** {item_group}\n\n"
            "開票前請先確認：**你是否已閱讀店內下單須知？**\n"
            "只有確認已閱讀後才會建立私人票口。\n\n"
            "票口建立後會沿用目前選擇的服務，再完成規格、陪玩人數與時長／數量。"
        ),
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=QuickOrderNoticeConfirmView(
            customer_id=interaction.user.id,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
            quick_module=quick_module,
        ),
        ephemeral=True,
    )


def install_quick_order_ticket_policy_20261028() -> None:
    """Require notice acknowledgement without changing quick-ticket self-service UI."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import quick_order_v2 as quick

    if not getattr(quick, "_order_notice_confirmation_installed", False):
        async def send_confirmation(
            interaction: discord.Interaction,
            *,
            category: str,
            item_group: str,
            source_channel_id: int,
        ):
            await _send_notice_confirmation(
                interaction,
                category=category,
                item_group=item_group,
                source_channel_id=source_channel_id,
                quick_module=quick,
            )

        quick._send_confirmation = send_confirmation
        quick._order_notice_confirmation_installed = True

    # Intentionally do not wrap quick._install_ticket_patch here. The owner chose
    # to keep quick-order tickets on their original locked-service self-service UI.
    _INSTALLED = True


__all__ = [
    "QuickOrderNoticeConfirmView",
    "install_quick_order_ticket_policy_20261028",
]
