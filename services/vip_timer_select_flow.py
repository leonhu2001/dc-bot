from __future__ import annotations

import time
from typing import Any

import discord

from services.vip_timer import VIP_TIMER_CATEGORY, VIP_TIMER_CATEGORY_LABEL


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None
_ORIGINAL_CATEGORY_STATE = None
_ORIGINAL_ITEM_GROUP_STATE = None
_CATALOG_CACHE_AT = 0.0
_CATALOG_CACHE: list[dict] | None = None
_CACHE_SECONDS = 2.0

_GAME_META = {
    "delta_desktop_basic": ("三角洲行動｜端遊", "基礎"),
    "delta_desktop_fun": ("三角洲行動｜端遊", "趣味"),
    "delta_mobile_basic": ("三角洲行動｜手遊", ""),
    "farm": ("三角洲行動｜代肝", ""),
    "steam": ("STEAM 遊戲", ""),
    "valorant": ("特戰英豪", ""),
    "lol": ("英雄聯盟", ""),
    "apex": ("APEX", ""),
    "custom": ("其他／自訂", ""),
}

_SERVICE_ORDER = {
    "單陪": 0,
    "雙陪": 1,
    "多人陪": 2,
    "甜蜜陪": 3,
    "教學單": 4,
    "其他": 9,
}


def _game_meta(category: str) -> tuple[str, str]:
    from services import orders

    key = str(category or "")
    if key in _GAME_META:
        return _GAME_META[key]
    return (str(orders.ORDER_CATEGORY_LABELS.get(key, key or "其他")), "")


def _staff_count(rule, detail: dict | None = None) -> int:
    detail = detail or {}
    raw = detail.get("player_count")
    try:
        if raw is not None:
            return max(1, int(raw))
    except (TypeError, ValueError):
        pass

    required = getattr(rule, "required_staff_count", 1)
    if required == "player_count":
        try:
            return max(1, int(getattr(rule, "min_player_count", 1) or 1))
        except (TypeError, ValueError):
            return 1
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return 1


def _service_type(source_group: str, detail: dict, rule) -> str:
    group_text = str(source_group or "")
    detail_text = str(detail.get("label") or "")
    rule_text = str(getattr(rule, "label", "") or "")
    text = f"{group_text}｜{detail_text}｜{rule_text}"

    if "甜蜜" in text:
        return "甜蜜陪"
    if "教學" in text or "導師" in text:
        return "教學單"

    count = _staff_count(rule, detail)
    if count == 1:
        return "單陪"
    if count == 2:
        return "雙陪"
    if count >= 3:
        return "多人陪"
    return "其他"


def _strip_count_words(text: str) -> str:
    result = str(text or "").strip()
    for token in (
        "｜陪玩1名",
        "｜陪玩2名",
        "｜陪玩3名",
        "｜陪玩4名",
        "陪玩1名",
        "陪玩2名",
        "陪玩3名",
        "陪玩4名",
    ):
        result = result.replace(token, "")
    return result.strip("｜ ")


def _spec_label(
    *,
    source_group: str,
    detail_label: str,
    variant: str,
    service_type: str,
) -> str:
    group_text = str(source_group or "").strip()
    detail_text = _strip_count_words(str(detail_label or "").strip())

    if service_type in {"單陪", "雙陪", "多人陪"}:
        for token in ("單陪", "雙陪"):
            detail_text = detail_text.replace(token, "").strip("｜ ")

    parts: list[str] = []
    if variant:
        parts.append(str(variant))
    if group_text and group_text not in {"甜蜜單", "教學單"}:
        parts.append(group_text)
    if detail_text and detail_text not in parts:
        parts.append(detail_text)

    if not parts:
        parts.append(service_type)
    return "｜".join(parts)[:100]


def _timer_detail_value(rule_key: str, player_count: int | None) -> str:
    return f"vt:{str(rule_key)}:{int(player_count or 0)}"[:100]


def _build_catalog_uncached() -> list[dict]:
    """Build a compact game -> eligible hourly rule catalog in one pass.

    The previous bridge called is_public_timer_rule() once per candidate. That
    function rescans the whole self-service catalog each time, which can make a
    Discord component callback miss the acknowledgement window. Resolve the
    eligible key set once, then classify each candidate locally.
    """
    from services import orders
    from services.order_rules import ORDER_RULES
    from services.vip_timer_catalog_guard import public_timer_rule_keys

    allowed_keys = set(public_timer_rule_keys())
    source_categories = [
        str(category)
        for category in orders.SELF_SERVICE_ACTIVE_CATEGORIES
        if str(category) != VIP_TIMER_CATEGORY
    ]

    grouped: dict[str, list[dict]] = {}
    seen: set[tuple[str, int]] = set()

    for source_category in source_categories:
        game_label, variant = _game_meta(source_category)
        for source_group in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(source_category, []):
            for source in orders.get_order_item_details_for_group(source_category, source_group):
                rule_key = str(source.get("rule_key") or "").strip()
                if not rule_key or rule_key not in allowed_keys:
                    continue
                rule = ORDER_RULES.get(rule_key)
                if rule is None:
                    continue

                try:
                    player_count = int(source.get("player_count") or 0)
                except (TypeError, ValueError):
                    player_count = 0
                unique = (rule_key, player_count)
                if unique in seen:
                    continue
                seen.add(unique)

                service_type = _service_type(str(source_group or ""), source, rule)
                spec_label = _spec_label(
                    source_group=str(source_group or ""),
                    detail_label=str(source.get("label") or getattr(rule, "label", rule_key)),
                    variant=variant,
                    service_type=service_type,
                )

                item = dict(source)
                item.update(
                    {
                        "label": spec_label,
                        "value": _timer_detail_value(rule_key, player_count),
                        "rule_key": rule_key,
                        "item": str(getattr(rule, "label", rule_key) or rule_key),
                        "quantity_unit": "計時",
                        "min_quantity": 1,
                        "max_quantity": 1,
                        "vip_timer": True,
                        "vip_timer_source_category": source_category,
                        "vip_timer_service_type": service_type,
                        "vip_timer_spec_label": spec_label,
                    }
                )
                if player_count > 0:
                    item["player_count"] = player_count
                else:
                    item.pop("player_count", None)
                grouped.setdefault(game_label, []).append(item)

    # Keep manager-created public hourly products available without creating a
    # second price table. Their canonical rule remains the pricing source.
    is_custom = getattr(ORDER_RULES, "is_custom", None)
    if callable(is_custom):
        for rule_key, rule in ORDER_RULES.items():
            key = str(rule_key or "").strip()
            if not key or key not in allowed_keys:
                continue
            try:
                if not bool(is_custom(key)):
                    continue
            except Exception:
                continue

            source_category = str(getattr(rule, "category", "") or "")
            game_label, variant = _game_meta(source_category)
            group_label = str(getattr(rule, "catalog_group_label", "") or "後台新增商品")
            if bool(getattr(rule, "player_count_enabled", False)):
                minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
                maximum_raw = getattr(rule, "max_player_count", None)
                maximum = int(maximum_raw) if maximum_raw is not None else minimum
                counts = range(minimum, min(maximum, 8) + 1)
            else:
                counts = (0,)

            for count in counts:
                unique = (key, int(count or 0))
                if unique in seen:
                    continue
                seen.add(unique)
                source = {
                    "label": str(getattr(rule, "label", key) or key),
                    "player_count": int(count) if count else None,
                }
                service_type = _service_type(group_label, source, rule)
                spec_label = _spec_label(
                    source_group=group_label,
                    detail_label=str(getattr(rule, "label", key) or key),
                    variant=variant,
                    service_type=service_type,
                )
                grouped.setdefault(game_label, []).append(
                    {
                        "label": spec_label,
                        "value": _timer_detail_value(key, int(count or 0)),
                        "rule_key": key,
                        "item": str(getattr(rule, "label", key) or key),
                        "player_count": int(count) if count else None,
                        "quantity_unit": "計時",
                        "min_quantity": 1,
                        "max_quantity": 1,
                        "vip_timer": True,
                        "vip_timer_source_category": source_category,
                        "vip_timer_service_type": service_type,
                        "vip_timer_spec_label": spec_label,
                    }
                )

    result: list[dict] = []
    for game_label in sorted(grouped):
        details = sorted(
            grouped[game_label],
            key=lambda row: (
                _SERVICE_ORDER.get(str(row.get("vip_timer_service_type") or "其他"), 99),
                str(row.get("label") or ""),
                str(row.get("value") or ""),
            ),
        )
        if details:
            result.append({"label": game_label[:100], "details": details})
    return result


def build_vip_timer_self_service_catalog() -> list[dict]:
    return _build_catalog_uncached()


def _cached_catalog() -> list[dict]:
    global _CATALOG_CACHE_AT, _CATALOG_CACHE
    now = time.monotonic()
    if _CATALOG_CACHE is None or now - _CATALOG_CACHE_AT >= _CACHE_SECONDS:
        _CATALOG_CACHE = _build_catalog_uncached()
        _CATALOG_CACHE_AT = now
    return [
        {"label": str(group.get("label") or ""), "details": [dict(row) for row in group.get("details", [])]}
        for group in _CATALOG_CACHE
    ]


def refresh_vip_timer_self_service_catalog() -> None:
    from services import order_runtime, orders

    catalog = _cached_catalog()
    orders.ORDER_CATEGORY_LABELS[VIP_TIMER_CATEGORY] = VIP_TIMER_CATEGORY_LABEL
    orders.SELF_SERVICE_ORDER_CATALOG[VIP_TIMER_CATEGORY] = catalog

    categories = tuple(
        category
        for category in orders.SELF_SERVICE_ACTIVE_CATEGORIES
        if str(category) != VIP_TIMER_CATEGORY
    ) + (VIP_TIMER_CATEGORY,)
    orders.SELF_SERVICE_ACTIVE_CATEGORIES = categories
    order_runtime.SELF_SERVICE_ACTIVE_CATEGORIES = categories
    order_runtime.ORDER_CATEGORY_LABELS[VIP_TIMER_CATEGORY] = VIP_TIMER_CATEGORY_LABEL


def _details_for_game(game_label: str | None) -> list[dict]:
    from services import orders

    if not game_label:
        return []
    return [dict(row) for row in orders.get_order_item_details_for_group(VIP_TIMER_CATEGORY, game_label)]


def _service_pages(details: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for detail in details:
        service_type = str(detail.get("vip_timer_service_type") or "其他")
        grouped.setdefault(service_type, []).append(detail)

    result: list[dict] = []
    for service_type in sorted(grouped, key=lambda key: (_SERVICE_ORDER.get(key, 99), key)):
        rows = grouped[service_type]
        total_pages = max(1, (len(rows) + 24) // 25)
        for page_index, offset in enumerate(range(0, len(rows), 25), start=1):
            chunk = rows[offset : offset + 25]
            label = service_type if total_pages == 1 else f"{service_type}｜{page_index}/{total_pages}"
            result.append(
                {
                    "service_type": service_type,
                    "page": page_index,
                    "label": label,
                    "value": f"{service_type}::{page_index}",
                    "details": chunk,
                }
            )
    return result


def _selected_service_page(data: dict) -> dict | None:
    game = str(data.get("item_group") or "")
    service_type = str(data.get("vip_timer_service_type") or "")
    page = int(data.get("vip_timer_service_page") or 1)
    for row in _service_pages(_details_for_game(game)):
        if row["service_type"] == service_type and int(row["page"]) == page:
            return row
    return None


def _effective_rate(detail: dict) -> int:
    from services.order_rules import ORDER_RULES

    rule = ORDER_RULES.get(str(detail.get("rule_key") or ""))
    if rule is None:
        return 0
    rate = int(getattr(rule, "price", 0) or 0)
    if bool(getattr(rule, "price_multiply_player_count", False)):
        try:
            rate *= max(1, int(detail.get("player_count") or 1))
        except (TypeError, ValueError):
            pass
    return rate


def _can_operate(interaction: discord.Interaction, customer_id: int) -> bool:
    from core.permissions import can_operate_self_service_order

    return bool(can_operate_self_service_order(interaction.user, customer_id))


class VipTimerServiceTypeSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        game = str(data.get("item_group") or "")
        pages = _service_pages(_details_for_game(game)) if game else []
        selected_type = str(data.get("vip_timer_service_type") or "")
        selected_page = int(data.get("vip_timer_service_page") or 1)

        if not game:
            options = [discord.SelectOption(label="請先選擇遊戲", value="need_game")]
            disabled = True
            placeholder = "請先選擇遊戲"
        elif not pages:
            options = [discord.SelectOption(label="這個遊戲目前沒有可用計時玩法", value="no_service")]
            disabled = True
            placeholder = "沒有可用陪玩形式"
        else:
            options = [
                discord.SelectOption(
                    label=str(row["label"])[:100],
                    value=str(row["value"])[:100],
                    description="選完後再選具體玩法"[:100],
                    default=(row["service_type"] == selected_type and int(row["page"]) == selected_page),
                )
                for row in pages[:25]
            ]
            disabled = False
            placeholder = "選擇陪玩形式"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_service_type_select",
            row=2,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        value = str((self.values or [""])[0])
        if value in {"need_game", "no_service", ""}:
            await interaction.response.defer()
            return

        service_type, _, page_text = value.partition("::")
        try:
            page = max(1, int(page_text or 1))
        except ValueError:
            page = 1

        from services import order_runtime

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        for key in ("item_detail_value", "item", "order_rule_key", "player_count", "specified_staff_ids", "payment_method"):
            data.pop(key, None)
        data["quantity"] = 1
        data["vip_timer_service_type"] = service_type
        data["vip_timer_service_page"] = page
        data["vip_timer_service_game"] = str(data.get("item_group") or "")
        state.remember_order(self.channel_id, data)

        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


class VipTimerRuleSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        service_page = _selected_service_page(data)
        selected_value = str(data.get("item_detail_value") or "")

        if service_page is None:
            options = [discord.SelectOption(label="請先選擇陪玩形式", value="need_service")]
            disabled = True
            placeholder = "請先選擇陪玩形式"
        else:
            details = list(service_page.get("details") or [])
            if not details:
                options = [discord.SelectOption(label="沒有可用玩法", value="no_rule")]
                disabled = True
                placeholder = "沒有可用玩法"
            else:
                options = []
                for detail in details[:25]:
                    rate = _effective_rate(detail)
                    description = f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"
                    options.append(
                        discord.SelectOption(
                            label=str(detail.get("vip_timer_spec_label") or detail.get("label") or "玩法")[:100],
                            value=str(detail.get("value") or "")[:100],
                            description=description[:100],
                            default=str(detail.get("value") or "") == selected_value,
                        )
                    )
                disabled = False
                placeholder = "選擇起始玩法／規格"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_rule_select",
            row=3,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected_value = str((self.values or [""])[0])
        if selected_value in {"need_service", "no_rule", ""}:
            await interaction.response.defer()
            return

        from services import order_runtime
        from services.self_service_selection_state import apply_self_service_detail_selection

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        service_page = _selected_service_page(data)
        detail = next(
            (
                row
                for row in list((service_page or {}).get("details") or [])
                if str(row.get("value") or "") == selected_value
            ),
            None,
        )
        if detail is None:
            await interaction.response.send_message("玩法選擇已更新，請重新選擇。", ephemeral=True)
            return

        apply_self_service_detail_selection(data, detail)
        data["quantity"] = 1
        data["vip_timer_order"] = True
        state.remember_order(self.channel_id, data)

        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


def build_vip_timer_self_service_panel_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    from services import orders

    game = str(data.get("item_group") or "尚未選擇")
    service_type = str(data.get("vip_timer_service_type") or "尚未選擇")
    detail = orders.get_order_item_detail_for_selection(
        VIP_TIMER_CATEGORY,
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    spec_label = str((detail or {}).get("vip_timer_spec_label") or (detail or {}).get("label") or "尚未選擇")

    embed = discord.Embed(
        title="自助下單｜VIP 自由計時",
        description=(
            f"下單用戶：<@{int(customer_id)}>\n\n"
            "金級會員以上限定。先選遊戲、陪玩形式與起始玩法；接滿後在票口開始計時。\n"
            "不預選時數，中途可切換遊戲／玩法，結束後依實際計時金額付款。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="第一欄｜類型", value="VIP 自由計時", inline=True)
    embed.add_field(name="第二欄｜遊戲", value=game, inline=True)
    embed.add_field(name="第三欄｜陪玩形式", value=service_type, inline=True)
    embed.add_field(name="第四欄｜起始玩法", value=spec_label, inline=True)
    embed.add_field(name="時間", value="自由計時｜不預選時數", inline=True)

    if detail:
        rate = _effective_rate(detail)
        embed.add_field(
            name="起始參考時薪",
            value=(f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"),
            inline=True,
        )
        embed.add_field(name="付款", value="結束計時後付款", inline=True)

    embed.set_footer(text="VIP 自由計時｜時間由票口計時器記錄，不用先選時數")
    return embed


def _install_selection_state_patch() -> None:
    global _ORIGINAL_CATEGORY_STATE, _ORIGINAL_ITEM_GROUP_STATE

    from services import order_runtime
    from services import self_service_selection_state as selection

    if _ORIGINAL_CATEGORY_STATE is None:
        _ORIGINAL_CATEGORY_STATE = selection.apply_self_service_category_selection
    if _ORIGINAL_ITEM_GROUP_STATE is None:
        _ORIGINAL_ITEM_GROUP_STATE = selection.apply_self_service_item_group_selection

    category_original = _ORIGINAL_CATEGORY_STATE
    item_original = _ORIGINAL_ITEM_GROUP_STATE

    def category_state(data: dict, category: str) -> None:
        category_original(data, category)
        for key in ("vip_timer_service_type", "vip_timer_service_page", "vip_timer_service_game"):
            data.pop(key, None)

    def item_group_state(data: dict, selected_group: str):
        result = item_original(data, selected_group)
        if str(data.get("category") or "") == VIP_TIMER_CATEGORY:
            for key in ("vip_timer_service_type", "vip_timer_service_page", "vip_timer_service_game"):
                data.pop(key, None)
        return result

    selection.apply_self_service_category_selection = category_state
    order_runtime.apply_self_service_category_selection = category_state
    selection.apply_self_service_item_group_selection = item_group_state
    order_runtime.apply_self_service_item_group_selection = item_group_state


def _install_view_patch() -> None:
    global _ORIGINAL_VIEW_INIT

    from services import self_service_ui_runtime as ui

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def timer_select_view_init(view, customer_id: int, channel_id: int, selected_category: str | None = None):
        original(view, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = str(selected_category or data.get("category") or "")
        if category != VIP_TIMER_CATEGORY:
            return

        for child in list(view.children):
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id in {"self_service_order_detail_select", "self_service_order_quantity_select"}:
                view.remove_item(child)
            elif custom_id == "self_service_order_item_select" and isinstance(child, discord.ui.Select):
                child.placeholder = "選擇遊戲"

        view.add_item(VipTimerServiceTypeSelect(customer_id, channel_id))
        view.add_item(VipTimerRuleSelect(customer_id, channel_id))

    ui.SelfServiceOrderView.__init__ = timer_select_view_init


def install_vip_timer_select_flow() -> None:
    """Refine the VIP timer self-service UI after the canonical bridge is installed."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_self_service as bridge

    bridge.build_vip_timer_self_service_catalog = build_vip_timer_self_service_catalog
    bridge.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog
    bridge.build_vip_timer_self_service_panel_embed = build_vip_timer_self_service_panel_embed

    refresh_vip_timer_self_service_catalog()
    _install_selection_state_patch()
    _install_view_patch()
    _INSTALLED = True


__all__ = [
    "VipTimerRuleSelect",
    "VipTimerServiceTypeSelect",
    "build_vip_timer_self_service_catalog",
    "build_vip_timer_self_service_panel_embed",
    "install_vip_timer_select_flow",
    "refresh_vip_timer_self_service_catalog",
]
