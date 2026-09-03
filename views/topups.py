from __future__ import annotations

import discord

from services.order_flow import get_payment_method_info
from services.topups import create_topup_order, submit_topup_payment


class TopupAmountModal(discord.ui.Modal, title="魔丸娛樂儲值"):
    amount = discord.ui.TextInput(label="儲值金額", placeholder="例如 12000", max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.amount.value).replace(",", "").strip())
            order = create_topup_order(
                customer_discord_id=interaction.user.id,
                customer_display_name=getattr(interaction.user, "display_name", interaction.user.name),
                amount=value,
                source="discord",
                payment_method="bank_transfer",
            )
        except (TypeError, ValueError) as exc:
            await interaction.response.send_message(str(exc) or "請輸入正確的儲值金額。", ephemeral=True)
            return

        payment_info = get_payment_method_info("轉帳") or "請聯絡客服取得付款資訊。"
        embed = discord.Embed(
            title=f"儲值單 {order['topup_no']}",
            description=(
                f"儲值金額：**{int(order['amount']):,}T**\n"
                "狀態：等待付款\n\n"
                f"```text\n{payment_info}\n```\n"
                "付款完成後請點下方「我已付款」，填寫銀行帳號末五碼。"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=TopupOrderView(int(order["id"])),
            ephemeral=True,
        )


class TopupPaymentModal(discord.ui.Modal, title="回報儲值付款"):
    bank_last5 = discord.ui.TextInput(label="銀行帳號末五碼", placeholder="12345", min_length=5, max_length=5)
    note = discord.ui.TextInput(label="付款備註（選填）", required=False, max_length=200)

    def __init__(self, topup_id: int):
        super().__init__()
        self.topup_id = int(topup_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            order = submit_topup_payment(
                self.topup_id,
                customer_discord_id=interaction.user.id,
                bank_last5=str(self.bank_last5.value),
                payment_note=str(self.note.value or ""),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ 儲值單 `{order['topup_no']}` 已送出付款資料，等待客服審核。",
            ephemeral=True,
        )


class TopupOrderView(discord.ui.View):
    def __init__(self, topup_id: int):
        super().__init__(timeout=900)
        self.topup_id = int(topup_id)

    @discord.ui.button(label="我已付款", style=discord.ButtonStyle.success)
    async def paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TopupPaymentModal(self.topup_id))


class TopupPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="我要儲值",
        style=discord.ButtonStyle.primary,
        custom_id="mawan_topup_open_v1",
        emoji="💰",
    )
    async def open_topup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TopupAmountModal())

    @discord.ui.button(
        label="網站錢包",
        style=discord.ButtonStyle.link,
        url="https://mowanentertainment.com/me/wallet",
    )
    async def website_wallet(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass
