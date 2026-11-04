from __future__ import annotations

import discord

from core.database import remember_order_data, save_bot_data
from core.permissions import is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RULE_KEY,
    NAMED_SELECTION_KEY,
    selected_ammo_dump_named,
)


class InternalAmmoNamedSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, channel_id: int, panel_message_id: int | None):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        super().__init__(
            custom_id="staff_internal_ammo_named_select",
            placeholder="請勾選有掛名／無掛名",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="☑ 有掛名｜顧客 2,650T",
                    value="named",
                    description="代肝 2,650T；店家差額 0T",
                ),
                discord.SelectOption(
                    label="☑ 無掛名｜顧客 3,000T",
                    value="unnamed",
                    description="代肝 2,650T；多出 350T 全給店家",
                ),
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服能勾選這張單的掛名狀態。", ephemeral=True)
            return
        if interaction.channel is None or int(interaction.channel.id) != self.channel_id:
            await interaction.response.send_message("只能在原訂單票口設定掛名狀態。", ephemeral=True)
            return

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id)
        if not isinstance(data, dict) or str(data.get("order_rule_key") or "") != AMMO_DUMP_RULE_KEY:
            await interaction.response.send_message("這張票口目前不是內部倒子彈 500M，請重新選擇商品。", ephemeral=True)
            return
        if data.get("dispatch_message_id") or str(data.get("status") or "").strip().lower() in {
            "waiting_acceptance", "accepted_pending_pay", "active", "stored", "completed", "cancelled"
        }:
            await interaction.response.send_message("此訂單已送出，不能再變更掛名與報價。", ephemeral=True)
            return

        named = self.values[0] == "named"
        data[NAMED_SELECTION_KEY] = named
        data["staff_internal_ammo_named_set_by"] = int(interaction.user.id)
        data["staff_internal_ammo_named_set_at"] = get_taipei_now_iso()
        data.pop("payment_method", None)

        remember_order_data(self.channel_id, data)
        save_bot_data()
        await interaction.response.defer(ephemeral=True)

        refreshed = False
        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel = await interaction.channel.fetch_message(self.panel_message_id)
                await panel.edit(
                    embed=ui.build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=ui.SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                refreshed = True
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            (
                "✅ 客服已勾選：有掛名｜顧客 2,650T｜代肝 2,650T｜店家差額 0T"
                if named
                else "✅ 客服已勾選：無掛名｜顧客 3,000T｜代肝 2,650T｜店家差額 350T"
            ) + ("" if refreshed else "\n⚠️ 訂單面板刷新失敗，請通知客服檢查。"),
            ephemeral=True,
        )
        try:
            from services.order_runtime import log_self_service_proxy_action
            await log_self_service_proxy_action(
                interaction,
                self.customer_id,
                "客服勾選倒子彈掛名狀態",
                "有掛名｜2,650T" if named else "無掛名｜3,000T（店抽350T）",
            )
        except Exception:
            pass


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


class InternalAmmoNamedButton(discord.ui.Button):
    def __init__(self, *, customer_id: int, channel_id: int, data: dict):
        named = selected_ammo_dump_named(data)
        label = (
            "客服勾選掛名｜待選擇"
            if named is None
            else "☑ 有掛名｜2,650T" if named else "☑ 無掛名｜3,000T"
        )
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary if named is None else discord.ButtonStyle.primary,
            custom_id="staff_internal_ammo_named_button",
            row=4,
        )
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以設定倒子彈的掛名狀態。", ephemeral=True)
            return

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id)
        if not isinstance(data, dict) or str(data.get("order_rule_key") or "") != AMMO_DUMP_RULE_KEY:
            await interaction.response.send_message("此票口已不是倒子彈 500M 商品。", ephemeral=True)
            return
        if data.get("dispatch_message_id"):
            await interaction.response.send_message("訂單已送出，不能再改掛名。", ephemeral=True)
            return

        await interaction.response.send_message(
            "請由客服勾選掛名狀態。未選擇前不能送單；代肝固定全額拿 2,650T。",
            view=InternalAmmoNamedView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=interaction.message.id if interaction.message else None,
            ),
            ephemeral=True,
        )


__all__ = [
    "InternalAmmoNamedButton",
    "InternalAmmoNamedView",
    "InternalAmmoNamedSelect",
]
