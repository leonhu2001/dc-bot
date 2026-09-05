from __future__ import annotations

import discord

from services.order_flow import get_payment_method_info
from services.topups import (
    create_topup_order,
    submit_topup_payment,
    topup_payment_method_label,
    topup_payment_reference_label,
)


_PAYMENT_INFO_KEYS = {
    "bank_transfer": "轉帳",
    "jkopay": "街口",
    "usdt_trc20": "USDT",
}


def _payment_info(payment_method: str) -> str:
    key = _PAYMENT_INFO_KEYS.get(str(payment_method or ""))
    return (get_payment_method_info(key) if key else None) or "請聯絡客服取得付款資訊。"


def _payment_instruction(payment_method: str) -> str:
    if payment_method == "bank_transfer":
        return "付款完成後請點下方「我已付款」，填寫銀行帳號末五碼。"
    if payment_method == "jkopay":
        return "付款完成後請點下方「我已付款」，填寫街口交易序號、付款人名稱或其他可辨識資訊。"
    if payment_method == "usdt_trc20":
        return (
            "請只使用 TRC20。儲值單金額以 T 顯示，實際 USDT 數量請先依客服當下換算確認後再轉帳。\n"
            "付款完成後請點下方「我已付款」，填寫 64 位交易 TXID。"
        )
    return "付款完成後請點下方「我已付款」回報付款資料。"


def _build_topup_embed(order: dict) -> discord.Embed:
    payment_method = str(order.get("payment_method") or "bank_transfer")
    payment_info = _payment_info(payment_method)
    return discord.Embed(
        title=f"儲值單 {order['topup_no']}",
        description=(
            f"儲值金額：**{int(order['amount']):,}T**\n"
            f"付款方式：**{topup_payment_method_label(payment_method)}**\n"
            "狀態：等待付款\n\n"
            f"\`\`\`text\n{payment_info}\n\`\`\`\n"
            f"{_payment_instruction(payment_method)}"
        ),
        color=discord.Color.gold(),
    )


class TopupAmountModal(discord.ui.Modal, title="魔丸娛樂儲值"):
    amount = discord.ui.TextInput(label="儲值金額", placeholder="例如 12000", max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.amount.value).replace(",", "").strip())
            if value <= 0:
                raise ValueError("儲值金額必須大於 0。")
            if value > 1_000_000:
                raise ValueError("單筆儲值金額超過系統上限，請聯絡客服。")
        except (TypeError, ValueError) as exc:
            await interaction.response.send_message(
                str(exc) or "請輸入正確的儲值金額。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="選擇儲值付款方式",
            description=(
                f"儲值金額：**{value:,}T**\n\n"
                "請選擇這筆儲值要使用的付款方式。"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=TopupPaymentMethodView(value),
            ephemeral=True,
        )


class TopupPaymentMethodView(discord.ui.View):
    def __init__(self, amount: int):
        super().__init__(timeout=300)
        self.amount = int(amount)

    async def _create(self, interaction: discord.Interaction, payment_method: str):
        try:
            order = create_topup_order(
                customer_discord_id=interaction.user.id,
                customer_display_name=getattr(
                    interaction.user,
                    "display_name",
                    interaction.user.name,
                ),
                amount=self.amount,
                source="discord",
                payment_method=payment_method,
            )
        except (TypeError, ValueError) as exc:
            await interaction.response.send_message(
                str(exc) or "建立儲值單失敗。",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=_build_topup_embed(order),
            view=TopupOrderView(int(order["id"]), payment_method),
        )

    @discord.ui.button(label="銀行轉帳", style=discord.ButtonStyle.primary, emoji="🏦")
    async def bank_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create(interaction, "bank_transfer")

    @discord.ui.button(label="街口支付", style=discord.ButtonStyle.primary, emoji="📱")
    async def jkopay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create(interaction, "jkopay")

    @discord.ui.button(label="USDT TRC20", style=discord.ButtonStyle.primary, emoji="🪙")
    async def usdt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create(interaction, "usdt_trc20")


class TopupPaymentModal(discord.ui.Modal):
    def __init__(self, topup_id: int, payment_method: str):
        super().__init__(title="回報儲值付款")
        self.topup_id = int(topup_id)
        self.payment_method = str(payment_method or "bank_transfer")

        if self.payment_method == "bank_transfer":
            self.reference = discord.ui.TextInput(
                label="銀行帳號末五碼",
                placeholder="12345",
                min_length=5,
                max_length=5,
            )
        elif self.payment_method == "jkopay":
            self.reference = discord.ui.TextInput(
                label="街口付款辨識資訊",
                placeholder="交易序號 / 付款人名稱",
                min_length=1,
                max_length=100,
            )
        elif self.payment_method == "usdt_trc20":
            self.reference = discord.ui.TextInput(
                label="交易 TXID",
                placeholder="64 位 TRC20 交易 TXID",
                min_length=64,
                max_length=64,
            )
        else:
            self.reference = discord.ui.TextInput(
                label=topup_payment_reference_label(self.payment_method),
                placeholder="付款辨識資訊",
                min_length=1,
                max_length=100,
            )

        self.note = discord.ui.TextInput(
            label="付款備註（選填）",
            required=False,
            max_length=200,
        )
        self.add_item(self.reference)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            order = submit_topup_payment(
                self.topup_id,
                customer_discord_id=interaction.user.id,
                payment_reference=str(self.reference.value),
                payment_note=str(self.note.value or ""),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ 儲值單 \`{order['topup_no']}\` 已送出付款資料，等待客服審核。",
            ephemeral=True,
        )


class TopupOrderView(discord.ui.View):
    def __init__(self, topup_id: int, payment_method: str):
        super().__init__(timeout=900)
        self.topup_id = int(topup_id)
        self.payment_method = str(payment_method or "bank_transfer")

    @discord.ui.button(label="我已付款", style=discord.ButtonStyle.success)
    async def paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TopupPaymentModal(self.topup_id, self.payment_method)
        )


class TopupPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="網站錢包",
                style=discord.ButtonStyle.link,
                url="https://mowanentertainment.com/me/wallet",
            )
        )

    @discord.ui.button(
        label="我要儲值",
        style=discord.ButtonStyle.primary,
        custom_id="mawan_topup_open_v1",
        emoji="💰",
    )
    async def open_topup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TopupAmountModal())
