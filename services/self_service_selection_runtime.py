from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord

from services.point_benefit_catalog import (
    POINT_BENEFIT_SPECS as ORDER_POINT_BENEFIT_SPECS,
    POINT_REDEEM_ITEMS as CANONICAL_POINT_REDEEM_ITEMS,
)
from services.self_service_favorite_priority import (
    prioritize_specified_staff_entries_for_customer,
)


_CONFIGURED = False
SELF_SERVICE_ORDER_SELECTIONS: dict = {}
POINT_REDEEM_ITEMS: list[dict] = []


def _unconfigured(*args, **kwargs):
    raise RuntimeError("self-service selection runtime is not configured")


_role_key_for_member: Callable[..., Any] = _unconfigured
remember_order_data: Callable[..., Any] = _unconfigured
build_self_service_panel_embed: Callable[..., Any] = _unconfigured
SelfServiceOrderView: Any = None
_to_int: Callable[..., Any] = _unconfigured
get_order_point_item: Callable[..., Any] = _unconfigured
get_customer_point_balance_for_order: Callable[..., Any] = _unconfigured
is_order_point_benefit_allowed_for_rule: Callable[..., Any] = _unconfigured
_adapt_order_point_benefit_for_rule: Callable[..., Any] = _unconfigured
get_selected_order_point_benefit: Callable[..., Any] = _unconfigured


def configure_self_service_selection_runtime(
    *,
    order_selections: dict,
    point_redeem_items: list[dict],
    role_key_for_member: Callable[..., Any],
    remember_data: Callable[..., Any],
    panel_embed_builder: Callable[..., Any],
    order_view_type: Any,
    to_int: Callable[..., Any],
    order_point_item_getter: Callable[..., Any],
    customer_point_balance_getter: Callable[..., Any],
    point_benefit_allowed_for_rule: Callable[..., Any],
    point_benefit_adapter: Callable[..., Any],
    selected_point_benefit_getter: Callable[..., Any],
) -> None:
    global _CONFIGURED
    global SELF_SERVICE_ORDER_SELECTIONS, POINT_REDEEM_ITEMS
    global _role_key_for_member, remember_order_data
    global build_self_service_panel_embed, SelfServiceOrderView, _to_int
    global get_order_point_item, get_customer_point_balance_for_order
    global is_order_point_benefit_allowed_for_rule
    global _adapt_order_point_benefit_for_rule, get_selected_order_point_benefit

    if order_view_type is None:
        raise RuntimeError("self-service selection runtime requires order_view_type")

    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    # The old bot.py list is intentionally ignored here. This module owns the
    # order-checkout catalog now so Discord and web can share one canonical source.
    POINT_REDEEM_ITEMS = [dict(item) for item in CANONICAL_POINT_REDEEM_ITEMS]
    _role_key_for_member = role_key_for_member
    remember_order_data = remember_data
    build_self_service_panel_embed = panel_embed_builder
    SelfServiceOrderView = order_view_type
    _to_int = to_int
    get_order_point_item = order_point_item_getter
    get_customer_point_balance_for_order = customer_point_balance_getter
    is_order_point_benefit_allowed_for_rule = point_benefit_allowed_for_rule
    _adapt_order_point_benefit_for_rule = point_benefit_adapter
    get_selected_order_point_benefit = selected_point_benefit_getter
    _CONFIGURED = True


SPECIFIED_STAFF_SELECT_PAGE_SIZE = 25

SPECIFIED_STAFF_ROLE_LABELS = {
    "top_protector": "魔丸♛頂護",
    "female_protector": "魔丸♝女護",
    "male_protector": "魔丸♜男護",
    "male_companion": "魔丸♞男陪",
    "female_companion": "魔丸♟女陪",
}


def _truncate_select_text(value: str, limit: int = 100) -> str:
    text_value = str(value or "").strip()

    if len(text_value) <= limit:
        return text_value

    return text_value[: limit - 1] + "…"


def get_specified_staff_entries_for_rule(guild: discord.Guild, rule) -> list[dict]:
    from services.order_rules import ALL_ROLE_IDS, ALL_ROLE_LABELS, get_allowed_role_keys

    entries = []
    allowed_role_keys = list(get_allowed_role_keys(rule))

    for member in guild.members:
        if getattr(member, "bot", False):
            continue

        member_role_ids = {
            str(role.id)
            for role in getattr(member, "roles", [])
            if getattr(role, "id", None) is not None
        }

        matched_role_keys = [
            role_key
            for role_key in allowed_role_keys
            if str(ALL_ROLE_IDS.get(role_key)) in member_role_ids
        ]

        if not matched_role_keys:
            continue

        display_role_key = _role_key_for_member(rule, member) or matched_role_keys[0]
        role_label = (
            SPECIFIED_STAFF_ROLE_LABELS.get(display_role_key)
            or ALL_ROLE_LABELS.get(display_role_key, display_role_key)
        )

        entries.append({
            "id": str(member.id),
            "label": _truncate_select_text(getattr(member, "display_name", None) or getattr(member, "name", None) or str(member.id)),
            "description": _truncate_select_text(role_label),
            "role_order": allowed_role_keys.index(display_role_key) if display_role_key in allowed_role_keys else 999,
        })

    entries.sort(key=lambda item: (item["role_order"], item["label"].casefold(), item["id"]))
    return entries


async def _acknowledge_component_interaction(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.HTTPException:
        pass


async def _edit_component_message(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    view: discord.ui.View | None = None,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=content, view=view)
        else:
            await interaction.response.edit_message(content=content, view=view)
    except discord.NotFound:
        pass
    except discord.HTTPException as exc:
        try:
            await interaction.followup.send(f"更新指定人員選單失敗：{exc}", ephemeral=True)
        except discord.HTTPException:
            pass


class SelfServiceSpecifiedStaffDropdown(discord.ui.Select):
    def __init__(self, parent_view: "SelfServiceSpecifiedStaffDropdownView"):
        entries = parent_view.page_entries()
        selected_ids = set(parent_view.selected_ids)

        if entries:
            options = [
                discord.SelectOption(
                    label=entry["label"],
                    value=entry["id"],
                    description=entry["description"],
                    default=entry["id"] in selected_ids,
                )
                for entry in entries
            ]
            disabled = False
            max_values = min(parent_view.max_specified_count, len(options))
        else:
            options = [
                discord.SelectOption(
                    label="這一頁沒有可指定人員",
                    value="none",
                    description="請換頁或通知客服確認身分組",
                )
            ]
            disabled = True
            max_values = 1

        super().__init__(
            placeholder=f"選擇指定人員，最多 {parent_view.max_specified_count} 位",
            min_values=1,
            max_values=max_values,
            options=options,
            disabled=disabled,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        if "none" in self.values:
            await interaction.response.defer()
            return

        page_ids = {entry["id"] for entry in view.page_entries()}
        current_ids = [
            staff_id
            for staff_id in view.selected_ids
            if staff_id not in page_ids
        ]

        for staff_id in self.values:
            if staff_id not in current_ids:
                current_ids.append(staff_id)

        if len(current_ids) > view.max_specified_count:
            await interaction.response.send_message(
                f"這張單最多只能指定 {view.max_specified_count} 位。",
                ephemeral=True,
            )
            return

        view.selected_ids = current_ids
        await view.save_selection_and_refresh_panel(interaction)

        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffPageButton(discord.ui.Button):
    def __init__(self, direction: int):
        self.direction = direction
        label = "上一頁" if direction < 0 else "下一頁"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        view.page = max(0, min(view.max_page, view.page + self.direction))
        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffClearButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="清除指定",
            style=discord.ButtonStyle.danger,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        view.selected_ids = []
        await view.save_selection_and_refresh_panel(interaction)
        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffDoneButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="完成",
            style=discord.ButtonStyle.success,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        await view.save_selection_and_refresh_panel(interaction)

        await interaction.response.edit_message(
            content="已完成指定人員設定，原本的自助下單面板已更新。",
            view=None,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


FREE_PLAY_FIRST_HOUR_RULE_KEYS = {
    "basic_entertain_single",
    "basic_entertain_double",
    "basic_tech_secret_single",
    "basic_tech_secret_double",
}


def _same_order_benefit_option_text(benefit: dict | None) -> str:
    if not benefit:
        return "本單累積福利"

    kind = str(benefit.get("benefit_kind") or "")
    try:
        units = float(benefit.get("benefit_units") or 0)
    except (TypeError, ValueError):
        units = 0.0

    if kind == "extra_hours":
        if abs(units - 0.5) < 0.001:
            benefit_text = "折抵 30 分鐘"
        else:
            benefit_text = f"折抵 {units:g} 小時"
    else:
        benefit_text = f"折抵 {int(round(units))} 局"

    return f"本單累積福利｜{benefit_text}"


class SelfServicePointBenefitSelect(discord.ui.Select):
    def __init__(self, parent_view: "SelfServicePointBenefitView"):
        options = [
            discord.SelectOption(
                label="不使用福利",
                value="none",
                description="清除這張單目前選擇的點數 / 會員福利",
                default=(
                    parent_view.selected_key is None
                    and parent_view.selected_coupon_id is None
                    and parent_view.selected_vip_monthly_benefit_id is None
                    and not parent_view.selected_same_order_benefit
                ),
            )
        ]

        for benefit in parent_view.available_vip_monthly_benefits:
            amount = int(benefit.get("amount") or 0)
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(str(benefit.get("title") or "VIP 每月折現券")),
                    value=f"vip_monthly:{benefit['id']}",
                    description=_truncate_select_text(f"折抵 {amount}T；與其他福利擇一"),
                    default=str(benefit.get("id")) == str(parent_view.selected_vip_monthly_benefit_id),
                )
            )

        if parent_view.available_same_order_benefit:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(
                        _same_order_benefit_option_text(parent_view.available_same_order_benefit)
                    ),
                    value="same_order",
                    description="本單達成累積門檻，可立即折抵；與其他福利擇一",
                    default=parent_view.selected_same_order_benefit,
                )
            )

        for coupon in parent_view.available_coupons:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(str(coupon.get("title") or "會員福利券")),
                    value=f"coupon:{coupon['id']}",
                    description="使用累積福利券；與點數福利擇一",
                    default=str(coupon.get("id")) == str(parent_view.selected_coupon_id),
                )
            )

        for item in parent_view.available_items:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(f"{item['cost']} 點｜{item['name']}"),
                    value=f"point:{item['key']}",
                    description=_truncate_select_text(item.get("summary") or f"兌換 {item['name']}"),
                    default=str(item["key"]) == str(parent_view.selected_key),
                )
            )

        if len(options) == 1:
            options[0].description = "目前沒有符合點數與訂單條件的福利"

        super().__init__(
            placeholder="選擇點數 / 會員福利",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServicePointBenefitView):
            await interaction.response.send_message("點數福利選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        selected = self.values[0]
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.channel_id, {})

        clear_keys = (
            "selected_point_benefit_key",
            "selected_benefit_coupon_id",
            "selected_vip_monthly_benefit_id",
            "selected_same_order_benefit",
            "vip_monthly_benefit_id",
            "vip_monthly_benefit_key",
            "vip_monthly_benefit_title",
            "vip_monthly_cash_amount",
            "point_benefit_key",
            "point_benefit_name",
            "point_benefit_cost",
            "point_discount_coupon_amount",
            "point_waived_specify_fee",
            "point_extra_hours",
            "point_extra_games",
            "service_bonus_text",
            "benefit_coupon_id",
            "benefit_coupon_title",
            "benefit_coupon",
            "benefit_discount_amount",
            "benefit_service_note",
        )
        for key in clear_keys:
            data.pop(key, None)

        if selected == "same_order":
            if view.available_same_order_benefit is None:
                await interaction.response.send_message(
                    "這張單目前尚未達到可立即折抵的累積門檻，請重新整理後再試。",
                    ephemeral=True,
                )
                return
            data["selected_same_order_benefit"] = True
        elif selected.startswith("vip_monthly:"):
            try:
                data["selected_vip_monthly_benefit_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("VIP 每月福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("coupon:"):
            try:
                data["selected_benefit_coupon_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("point:"):
            point_key = selected.split(":", 1)[1]
            item = get_order_point_item(point_key)
            if item is None:
                await interaction.response.send_message("找不到這個點數福利，請重新選擇。", ephemeral=True)
                return
            item = _adapt_order_point_benefit_for_rule(view.rule, item)
            data["selected_point_benefit_key"] = point_key
            data["point_benefit_key"] = point_key
            data["point_benefit_name"] = str(item.get("name") or point_key)
            data["point_benefit_cost"] = int(item.get("cost") or 0)

        data.pop("payment_method", None)
        remember_order_data(view.channel_id, data)

        await view.refresh_source_panel(interaction)

        await interaction.response.edit_message(
            content=view.build_message_content(data),
            view=SelfServicePointBenefitView(
                customer_id=view.customer_id,
                channel_id=view.channel_id,
                panel_message_id=view.panel_message_id,
                rule=view.rule,
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServicePointBenefitView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None,
        rule,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        self.rule = rule

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        data["customer_id"] = self.customer_id
        self.selected_key = data.get("selected_point_benefit_key")
        self.selected_coupon_id = data.get("selected_benefit_coupon_id")
        self.selected_vip_monthly_benefit_id = data.get("selected_vip_monthly_benefit_id")
        self.selected_same_order_benefit = bool(data.get("selected_same_order_benefit"))
        self.point_balance = get_customer_point_balance_for_order(customer_id)
        self.available_items = self.build_available_items(data)
        from services.loyalty_benefits import list_applicable_coupons, preview_same_order_benefit
        from services.vip_monthly_benefits import list_available_cash_benefits
        self.available_vip_monthly_benefits = list_available_cash_benefits(customer_id)
        self.available_coupons = list_applicable_coupons(
            customer_id,
            rule_key=str(getattr(rule, "key", "")),
            player_count=_to_int(data.get("player_count"), 1) or 1,
        )
        self.available_same_order_benefit = preview_same_order_benefit(
            customer_id,
            rule_key=str(getattr(rule, "key", "")),
            quantity=_to_int(data.get("quantity"), 1) or 1,
            player_count=_to_int(data.get("player_count"), 1) or 1,
        )
        if self.selected_same_order_benefit and self.available_same_order_benefit is None:
            self.selected_same_order_benefit = False
            data.pop("selected_same_order_benefit", None)
            remember_order_data(self.channel_id, data)

        self.add_item(SelfServicePointBenefitSelect(self))

    def build_available_items(self, data: dict) -> list[dict]:
        result = []

        try:
            source_items = POINT_REDEEM_ITEMS
        except Exception:
            source_items = []

        for item in source_items:
            key = str(item.get("key") or "")
            spec = ORDER_POINT_BENEFIT_SPECS.get(key)

            if not spec:
                continue

            allowed, _ = is_order_point_benefit_allowed_for_rule(self.rule, key, data)

            if not allowed:
                continue

            # Adapt first so dynamic formal-product pricing is authoritative before
            # comparing against the customer's balance. The previous runtime wrapper
            # existed only to repair this ordering after import.
            merged = dict(item)
            merged.update(spec)
            merged = _adapt_order_point_benefit_for_rule(
                self.rule,
                merged,
            )
            cost = int(merged.get("cost") or 0)
            if cost > self.point_balance:
                continue
            result.append(merged)

        return result

    def build_message_content(self, data: dict | None = None) -> str:
        data = data or SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        benefit = get_selected_order_point_benefit(data, self.rule)
        selected_text = "尚未使用"

        if data.get("selected_same_order_benefit") and self.available_same_order_benefit:
            selected_text = _same_order_benefit_option_text(self.available_same_order_benefit)
        elif data.get("selected_vip_monthly_benefit_id"):
            monthly = next(
                (
                    item
                    for item in self.available_vip_monthly_benefits
                    if str(item.get("id")) == str(data.get("selected_vip_monthly_benefit_id"))
                ),
                None,
            )
            if monthly:
                selected_text = str(monthly.get("title") or "VIP 每月折現券")
        elif data.get("selected_benefit_coupon_id"):
            coupon = next(
                (item for item in self.available_coupons if str(item.get("id")) == str(data.get("selected_benefit_coupon_id"))),
                None,
            )
            if coupon:
                selected_text = str(coupon.get("title") or "會員福利券")
        elif benefit:
            selected_text = f"{benefit['cost']} 點｜{benefit['name']}"

        return (
            f"請選擇這張單要使用的點數福利或會員福利券。\n"
            f"目前可用點數：{self.point_balance} 點\n"
            f"可用福利券：{len(self.available_vip_monthly_benefits) + len(self.available_coupons) + (1 if self.available_same_order_benefit else 0)} 張\n"
            f"目前選擇：{selected_text}\n\n"
            "同張訂單只能擇一；福利券會在訂單建立時先保留，結單後正式核銷。"
        )

    async def refresh_source_panel(self, interaction: discord.Interaction):
        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass


class SelfServiceSpecifiedStaffDropdownView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None,
        rule_key: str,
        max_specified_count: int,
        entries: list[dict],
        selected_ids: list[str] | None = None,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        self.rule_key = str(rule_key)
        self.max_specified_count = max(1, int(max_specified_count or 1))
        self.entries = prioritize_specified_staff_entries_for_customer(
            entries,
            self.customer_id,
        )
        self.selected_ids = list(dict.fromkeys(str(item) for item in (selected_ids or []) if str(item).strip()))
        self.page = 0
        self.refresh_items()

    @property
    def max_page(self) -> int:
        if not self.entries:
            return 0
        return max(0, (len(self.entries) - 1) // SPECIFIED_STAFF_SELECT_PAGE_SIZE)

    def page_entries(self) -> list[dict]:
        start = self.page * SPECIFIED_STAFF_SELECT_PAGE_SIZE
        end = start + SPECIFIED_STAFF_SELECT_PAGE_SIZE
        return self.entries[start:end]

    def refresh_items(self):
        self.clear_items()
        self.add_item(SelfServiceSpecifiedStaffDropdown(self))

        previous_button = SelfServiceSpecifiedStaffPageButton(-1)
        previous_button.disabled = self.page <= 0
        self.add_item(previous_button)

        next_button = SelfServiceSpecifiedStaffPageButton(1)
        next_button.disabled = self.page >= self.max_page
        self.add_item(next_button)

        self.add_item(SelfServiceSpecifiedStaffClearButton())
        self.add_item(SelfServiceSpecifiedStaffDoneButton())

    def selected_mentions(self) -> list[str]:
        return [f"<@{staff_id}>" for staff_id in self.selected_ids]

    def build_message_content(self) -> str:
        selected_text = "、".join(self.selected_mentions()) if self.selected_ids else "尚未指定"

        return (
            f"請從下拉式清單選擇指定人員。\n"
            f"目前頁數：{self.page + 1}/{self.max_page + 1}\n"
            f"最多可指定：{self.max_specified_count} 位\n"
            f"目前指定：{selected_text}"
        )

    async def save_selection_and_refresh_panel(self, interaction: discord.Interaction):
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        data["specified_staff_ids"] = self.selected_ids

        if self.selected_ids:
            data["companion_preference"] = "指定陪玩/打手"
        else:
            data["companion_preference"] = "不指定陪玩/打手"

        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass
