from __future__ import annotations

import discord

from core.database import remember_order_data
from core.permissions import can_operate_self_service_order
from services import order_runtime
from services.multi_seat_order_policy_20261028 import (
    get_rule_player_count_bounds,
    normalize_rule_player_count,
)
from services.self_service_point_benefits import is_order_point_benefit_allowed_for_rule
from services.self_service_selection_state import apply_self_service_category_selection
from services import self_service_ui_runtime as base_ui


_INSTALLED = False


class SelfServicePlayerCountSelect(discord.ui.Select):
    def __init__(self, parent: "SelfServicePlayerCountView"):
        minimum, maximum, default, selectable = get_rule_player_count_bounds(parent.rule)
        current = normalize_rule_player_count(parent.rule, parent.current_count)
        options = [
            discord.SelectOption(
                label=f"{count} 人",
                value=str(count),
                description=f"需要 {count} 位陪玩／打手",
                default=count == current,
            )
            for count in range(minimum, maximum + 1)
        ]
        super().__init__(
            placeholder=f"陪玩人數 {minimum}～{maximum} 人",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not selectable,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, SelfServicePlayerCountView):
            await interaction.response.send_message("陪玩人數選單狀態異常，請重新操作。", ephemeral=True)
            return

        try:
            selected = int(self.values[0])
        except (TypeError, ValueError):
            await interaction.response.send_message("陪玩人數選擇異常，請重新操作。", ephemeral=True)
            return

        minimum, maximum, default, selectable = get_rule_player_count_bounds(view.rule)
        if not selectable or selected < minimum or selected > maximum:
            await interaction.response.send_message(
                f"這個商品的陪玩人數只能選 {minimum}～{maximum} 人。",
                ephemeral=True,
            )
            return

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(view.channel_id, {})
        data["player_count"] = selected
        data.pop("payment_method", None)

        specified_ids = [str(item) for item in data.get("specified_staff_ids") or []]
        if len(specified_ids) > selected:
            data["specified_staff_ids"] = specified_ids[:selected]
        if not data.get("specified_staff_ids"):
            data["companion_preference"] = "不指定陪玩/打手"

        selected_point_key = str(data.get("selected_point_benefit_key") or "")
        if selected_point_key:
            allowed, _reason = is_order_point_benefit_allowed_for_rule(
                view.rule,
                selected_point_key,
                data,
            )
            if not allowed:
                data.pop("selected_point_benefit_key", None)
                data.pop("point_benefit_key", None)
                data.pop("point_benefit_name", None)
                data.pop("point_benefit_cost", None)
                data.pop("point_extra_hours", None)
                data.pop("point_extra_games", None)
                data.pop("service_bonus_text", None)

        remember_order_data(view.channel_id, data)

        if isinstance(interaction.channel, discord.TextChannel) and view.panel_message_id:
            try:
                panel = await interaction.channel.fetch_message(view.panel_message_id)
                await panel.edit(
                    embed=base_ui.build_self_service_panel_embed(
                        view.customer_id,
                        data,
                        interaction.guild,
                    ),
                    view=EnhancedSelfServiceOrderView(
                        customer_id=view.customer_id,
                        channel_id=view.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        await interaction.response.edit_message(
            content=f"已設定陪玩人數：**{selected} 人**。",
            view=None,
        )


class SelfServicePlayerCountView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None,
        rule,
        current_count: int | None,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        self.rule = rule
        self.current_count = current_count
        self.add_item(SelfServicePlayerCountSelect(self))


class SelfServicePlayerCountButton(discord.ui.Button):
    def __init__(self, *, rule, current_count: int | None, disabled: bool):
        minimum, maximum, default, selectable = get_rule_player_count_bounds(rule)
        count = normalize_rule_player_count(rule, current_count)
        label = "陪玩人數" if rule is None else f"陪玩人數：{count}"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            custom_id="self_service_order_player_count_button",
            row=3,
            disabled=bool(disabled or not selectable),
        )
        self.rule = rule

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, EnhancedSelfServiceOrderView):
            await interaction.response.send_message("陪玩人數按鈕狀態異常，請重新操作。", ephemeral=True)
            return
        if not can_operate_self_service_order(interaction.user, view.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇陪玩人數。", ephemeral=True)
            return
        if self.rule is None:
            await interaction.response.send_message("請先選擇具體規格。", ephemeral=True)
            return

        data = order_runtime._require_runtime_state().order_selections.setdefault(view.channel_id, {})
        minimum, maximum, default, selectable = get_rule_player_count_bounds(self.rule)
        if not selectable:
            await interaction.response.send_message(
                f"這個商品固定需要 {default} 人，不開放調整。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=f"請選擇陪玩人數（可選 {minimum}～{maximum} 人）。",
            view=SelfServicePlayerCountView(
                customer_id=view.customer_id,
                channel_id=view.channel_id,
                panel_message_id=(interaction.message.id if interaction.message else None),
                rule=self.rule,
                current_count=data.get("player_count"),
            ),
            ephemeral=True,
        )


def _install_change_category_option(item_select, enhanced_view: "EnhancedSelfServiceOrderView") -> None:
    if not getattr(item_select, "options", None):
        return
    if any(str(option.value) == "__change_category__" for option in item_select.options):
        return

    item_select.options = [
        discord.SelectOption(
            label="← 重新選擇類別",
            value="__change_category__",
            description="回到第一欄重新選擇訂單類別",
        ),
        *list(item_select.options)[:24],
    ]
    original_callback = item_select.callback

    async def callback(interaction: discord.Interaction):
        if "__change_category__" not in item_select.values:
            await original_callback(interaction)
            return
        if not can_operate_self_service_order(interaction.user, enhanced_view.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以重新選擇類別。", ephemeral=True)
            return

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(enhanced_view.channel_id, {})
        apply_self_service_category_selection(data, "")
        data.pop("category", None)
        state.remember_order(enhanced_view.channel_id, data)
        await interaction.response.edit_message(
            embed=base_ui.build_self_service_panel_embed(
                enhanced_view.customer_id,
                data,
                interaction.guild,
            ),
            view=EnhancedSelfServiceOrderView(
                customer_id=enhanced_view.customer_id,
                channel_id=enhanced_view.channel_id,
                selected_category=None,
            ),
        )

    item_select.callback = callback


class EnhancedSelfServiceOrderView(base_ui.SelfServiceOrderView):
    """Legacy-compatible panel with one shared player-count control.

    Discord legacy views have only five action rows. Once a category is selected we
    collapse the category selector into the embed and expose a return option in the
    item selector. That frees one row for the requested five action buttons and one
    final submit row without migrating the message to Components V2.
    """

    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        super().__init__(customer_id, channel_id, selected_category)

        state = order_runtime._require_runtime_state()
        data = state.order_selections.get(channel_id, {})
        category = selected_category or data.get("category")
        selected_item = data.get("item")
        try:
            current_rule = base_ui._get_rule_from_self_service_data(data) if selected_item else None
        except Exception:
            current_rule = None

        by_id = {
            str(getattr(child, "custom_id", "") or ""): child
            for child in list(self.children)
        }

        category_select = by_id.get("self_service_order_category_select")
        item_select = by_id.get("self_service_order_item_select")
        detail_select = by_id.get("self_service_order_detail_select")
        quantity_select = by_id.get("self_service_order_quantity_select")

        specified = by_id.get("self_service_order_specified_staff_button")
        point = by_id.get("self_service_order_point_benefit_button")
        staff_price = by_id.get("self_service_order_staff_price_button")
        discount = by_id.get("self_service_order_staff_discount_coupon_button")
        submit = by_id.get("self_service_order_go_payment_button")

        action_items = [item for item in (specified, point, staff_price, discount, submit) if item is not None]
        for item in action_items:
            self.remove_item(item)

        count_button = SelfServicePlayerCountButton(
            rule=current_rule,
            current_count=data.get("player_count"),
            disabled=current_rule is None,
        )

        if specified is not None:
            specified.label = "指定成員"
        if point is not None:
            point.label = "點數福利"
            if current_rule is None:
                point.disabled = True
        if staff_price is not None:
            staff_price.label = "客服填價"
        if discount is not None:
            discount.label = "手動折扣"
            if current_rule is None:
                discount.disabled = True
        if submit is not None:
            submit.label = "送出訂單"

        if category:
            # View weights cache the rendered row at add-time. Remove selects first,
            # then set their new rows and add them back; simply assigning item.row
            # would leave the old row occupied internally and can make row 3 reject
            # the new five-button action bar.
            for item in (category_select, item_select, detail_select, quantity_select):
                if item is not None:
                    self.remove_item(item)

            if item_select is not None:
                item_select.row = 0
                _install_change_category_option(item_select, self)
                self.add_item(item_select)
            if detail_select is not None:
                detail_select.row = 1
                self.add_item(detail_select)
            if quantity_select is not None:
                quantity_select.row = 2
                self.add_item(quantity_select)

            for item in (count_button, specified, point, staff_price, discount):
                if item is None:
                    continue
                item.row = 3
                self.add_item(item)

            if submit is not None:
                submit.row = 4
                original_submit = submit.callback

                async def submit_callback(interaction: discord.Interaction):
                    latest = state.order_selections.get(channel_id, {})
                    if latest.get("item"):
                        try:
                            rule = base_ui._get_rule_from_self_service_data(latest)
                        except Exception as exc:
                            await interaction.response.send_message(str(exc), ephemeral=True)
                            return

                        minimum, maximum, default, selectable = get_rule_player_count_bounds(rule)
                        current_count = normalize_rule_player_count(rule, latest.get("player_count"))
                        raw_count = latest.get("player_count")
                        if selectable and raw_count is None:
                            await interaction.response.send_message("請先按「陪玩人數」選擇人數。", ephemeral=True)
                            return
                        try:
                            raw_int = int(raw_count) if raw_count is not None else current_count
                        except (TypeError, ValueError):
                            raw_int = current_count
                        if raw_int < minimum or raw_int > maximum:
                            latest["player_count"] = default
                            state.remember_order(channel_id, latest)
                            await interaction.response.send_message(
                                f"目前陪玩人數已不適用這個商品，已重設為 {default} 人，請確認後再送出。",
                                ephemeral=True,
                            )
                            return

                        point_key = str(latest.get("selected_point_benefit_key") or "")
                        if point_key:
                            allowed, reason = is_order_point_benefit_allowed_for_rule(rule, point_key, latest)
                            if not allowed:
                                await interaction.response.send_message(
                                    reason or "目前選擇的點數福利已不適用，請重新選擇。",
                                    ephemeral=True,
                                )
                                return

                    await original_submit(interaction)

                submit.callback = submit_callback
                self.add_item(submit)
        else:
            # Before a category is selected the four selectors consume rows 0-3.
            # Keep the requested five controls visible on row 4; submit appears on
            # its own final row immediately after the category has been selected.
            for item in (count_button, specified, point, staff_price, discount):
                if item is None:
                    continue
                item.row = 4
                item.disabled = True
                self.add_item(item)


def install_self_service_companion_count_runtime():
    global _INSTALLED
    if _INSTALLED:
        return EnhancedSelfServiceOrderView
    base_ui.SelfServiceOrderView = EnhancedSelfServiceOrderView
    _INSTALLED = True
    return EnhancedSelfServiceOrderView


__all__ = [
    "EnhancedSelfServiceOrderView",
    "SelfServicePlayerCountView",
    "install_self_service_companion_count_runtime",
]
