from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import discord

from core.database import remember_order_data
from core.permissions import is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.order_runtime import log_self_service_proxy_action
from services.self_service_financials import (
    _format_percent_value,
    _format_plain_amount,
    _parse_cash_amount_text,
    _parse_discount_percent_text,
)


@dataclass(frozen=True)
class SelfServiceStaffPricingUIDeps:
    order_selections: dict[int, dict]
    panel_embed_builder: Callable
    order_view_type: type


_DEPS: SelfServiceStaffPricingUIDeps | None = None


def configure_self_service_staff_pricing_ui(
    *,
    order_selections: dict[int, dict],
    panel_embed_builder: Callable,
    order_view_type: type,
) -> None:
    global _DEPS
    _DEPS = SelfServiceStaffPricingUIDeps(
        order_selections=order_selections,
        panel_embed_builder=panel_embed_builder,
        order_view_type=order_view_type,
    )


def _require_deps() -> SelfServiceStaffPricingUIDeps:
    if _DEPS is None:
        raise RuntimeError("self-service staff pricing UI not configured")
    return _DEPS


async def _refresh_staff_pricing_panel(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
    panel_message_id: int | None,
    data: dict,
) -> bool:
    deps = _require_deps()

    if not isinstance(interaction.channel, discord.TextChannel) or not panel_message_id:
        return False

    try:
        panel_message = await interaction.channel.fetch_message(panel_message_id)
        await panel_message.edit(
            embed=deps.panel_embed_builder(
                customer_id,
                data,
                interaction.guild,
            ),
            view=deps.order_view_type(
                customer_id=customer_id,
                channel_id=channel_id,
                selected_category=data.get("category"),
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        return True
    except discord.HTTPException:
        return False


class SelfServiceStaffPriceModal(discord.ui.Modal, title="客服填寫訂單價格"):
    amount = discord.ui.TextInput(
        label="訂單價格",
        placeholder="請輸入實收前原價，例如 3000",
        required=True,
        max_length=10,
    )

    reason = discord.ui.TextInput(
        label="價格備註",
        placeholder="例如 自訂單報價、部門任務報價",
        required=False,
        max_length=100,
    )

    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None = None,
    ):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以填寫訂單價格。",
                ephemeral=True,
            )
            return

        raw_amount = str(self.amount.value or "").strip().replace(",", "")

        try:
            amount = int(float(raw_amount))
        except ValueError:
            await interaction.response.send_message(
                "價格請輸入數字，例如 3000。",
                ephemeral=True,
            )
            return

        if amount < 0:
            await interaction.response.send_message(
                "價格不能小於 0。",
                ephemeral=True,
            )
            return

        deps = _require_deps()
        data = deps.order_selections.setdefault(self.channel_id, {})
        data["manual_staff_amount"] = int(amount)
        data["manual_staff_price_reason"] = str(self.reason.value or "").strip()
        data["manual_staff_price_set_by"] = interaction.user.id
        data["manual_staff_price_set_at"] = get_taipei_now_iso()
        data.pop("payment_method", None)

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = await _refresh_staff_pricing_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=self.panel_message_id,
            data=data,
        )

        await interaction.followup.send(
            f"已設定訂單價格：{_format_plain_amount(amount)}"
            + (
                f"\n備註：{data['manual_staff_price_reason']}"
                if data.get("manual_staff_price_reason")
                else ""
            )
            + (
                ""
                if edited_panel
                else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"
            ),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "客服填寫訂單價格",
            f"{_format_plain_amount(amount)}｜"
            f"{data.get('manual_staff_price_reason') or '無備註'}",
        )


class SelfServiceStaffDiscountCouponModal(
    discord.ui.Modal,
    title="客服設定折扣",
):
    discount_percent = discord.ui.TextInput(
        label="折後比例 %",
        placeholder="例如 90 = 9 折；不折扣留空或填 100",
        required=False,
        max_length=10,
    )

    discount_reason = discord.ui.TextInput(
        label="折扣原因",
        placeholder="例如 VIP折扣、店內活動、老客優惠、補償折扣",
        required=False,
        max_length=100,
    )

    cash_coupon_amount = discord.ui.TextInput(
        label="固定折扣金額",
        placeholder="例如 100；沒有固定折扣可留空或填 0",
        required=False,
        max_length=10,
    )

    cash_coupon_reason = discord.ui.TextInput(
        label="固定折扣原因 / 名稱",
        placeholder="例如 VIP優惠、活動優惠、生日優惠",
        required=False,
        max_length=100,
    )

    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None = None,
    ):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以設定折扣。",
                ephemeral=True,
            )
            return

        deps = _require_deps()
        data = deps.order_selections.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message(
                "請先選擇訂單項目，再設定折扣。",
                ephemeral=True,
            )
            return

        discount_percent_text = str(
            self.discount_percent.value or ""
        ).strip()

        try:
            discount_percent = _parse_discount_percent_text(
                discount_percent_text
            )
            coupon_amount = _parse_cash_amount_text(
                str(self.cash_coupon_amount.value or "")
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if discount_percent_text:
            data["manual_discount_mode"] = "pay_rate"
            data["manual_discount_percent"] = discount_percent
            data["manual_discount_percent_override"] = True
            data["manual_discount_reason"] = str(
                self.discount_reason.value or ""
            ).strip()
        else:
            data.pop("manual_discount_mode", None)
            data.pop("manual_discount_percent", None)
            data.pop("manual_discount_reason", None)
            data["manual_discount_percent_override"] = False

        data["cash_coupon_amount"] = coupon_amount
        data["fixed_discount_amount"] = coupon_amount
        data["cash_coupon_reason"] = str(
            self.cash_coupon_reason.value or ""
        ).strip()
        data["manual_price_adjustment_set_by"] = interaction.user.id
        data["manual_price_adjustment_set_at"] = get_taipei_now_iso()

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = await _refresh_staff_pricing_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=self.panel_message_id,
            data=data,
        )

        adjustment_note: list[str] = []

        if discount_percent_text:
            adjustment_note.append(
                "客服百分比：折後 "
                f"{_format_percent_value(discount_percent)}%"
            )
        else:
            adjustment_note.append(
                "客服百分比已清除，改由顧客 VIP 等級自動套用。"
            )

        if coupon_amount > 0:
            adjustment_note.append(
                f"固定折扣：-{_format_plain_amount(coupon_amount)}"
                "（店內吸收，不影響打手分潤）"
            )

        await interaction.followup.send(
            "已設定折扣。"
            + (
                "\n" + "\n".join(adjustment_note)
                if adjustment_note
                else ""
            )
            + (
                ""
                if edited_panel
                else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"
            ),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "設定折扣",
            (
                "｜".join(adjustment_note)
                if adjustment_note
                else "折後100%，無固定折扣"
            ),
        )
