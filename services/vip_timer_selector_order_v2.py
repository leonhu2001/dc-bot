from __future__ import annotations

import hashlib
import re

import discord


_INSTALLED = False
_SPEC_PAGE_SIZE = 23


def _service_type(source_group: str, detail: dict, rule) -> str:
    group_text = str(source_group or "")
    detail_text = str(detail.get("label") or "")
    rule_text = str(getattr(rule, "label", "") or "")
    text = f"{group_text}｜{detail_text}｜{rule_text}"

    if "甜蜜" in text:
        return "甜蜜陪"
    if "教學" in text or "導師" in text:
        return "教學單"

    from services import vip_timer_select_flow as flow

    count = flow._staff_count(rule, detail)
    if count == 1:
        return "單陪"
    if count == 2:
        return "雙陪"
    if count >= 3:
        return f"{count}陪"
    return "其他"


def _spec_label(*, source_group: str, detail_label: str, variant: str, service_type: str) -> str:
    from services import vip_timer_select_flow as flow

    group_text = str(source_group or "").strip()
    detail_text = flow._strip_count_words(str(detail_label or "").strip())
    detail_text = re.sub(r"(?:單陪|雙陪|[3-9]陪)", "", detail_text).strip("｜ ")

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


def _spec_key(label: str) -> str:
    digest = hashlib.sha1(str(label).encode("utf-8")).hexdigest()[:16]
    return f"spec:{digest}"


def _spec_groups(details: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for detail in details:
        label = str(detail.get("vip_timer_spec_label") or detail.get("label") or "玩法").strip() or "玩法"
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label in sorted(grouped):
        rows = sorted(grouped[label], key=lambda row: str(row.get("value") or ""))
        result.append(
            {
                "key": _spec_key(label),
                "label": label[:100],
                "details": rows,
            }
        )
    return result


def _selected_spec_group(data: dict) -> dict | None:
    from services import vip_timer_select_flow as flow

    game = str(data.get("item_group") or "")
    selected = str(data.get("vip_timer_spec_key") or "")
    if not game or not selected:
        return None
    for group in _spec_groups(flow._details_for_game(game)):
        if str(group["key"]) == selected:
            return group
    return None


def _clear_final_selection(data: dict) -> None:
    for key in (
        "item_detail_value",
        "item",
        "order_rule_key",
        "player_count",
        "specified_staff_ids",
        "payment_method",
        "vip_timer_service_type",
        "vip_timer_service_page",
        "vip_timer_service_game",
    ):
        data.pop(key, None)
    data["quantity"] = 1


def _can_operate(interaction: discord.Interaction, customer_id: int) -> bool:
    from core.permissions import can_operate_self_service_order

    return bool(can_operate_self_service_order(interaction.user, customer_id))


class VipTimerGameplaySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui
        from services import vip_timer_select_flow as flow

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        game = str(data.get("item_group") or "")
        groups = _spec_groups(flow._details_for_game(game)) if game else []
        selected_key = str(data.get("vip_timer_spec_key") or "")
        try:
            page = max(1, int(data.get("vip_timer_spec_page") or 1))
        except (TypeError, ValueError):
            page = 1

        total_pages = max(1, (len(groups) + _SPEC_PAGE_SIZE - 1) // _SPEC_PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * _SPEC_PAGE_SIZE
        chunk = groups[start : start + _SPEC_PAGE_SIZE]

        if not game:
            options = [discord.SelectOption(label="請先選擇遊戲", value="need_game")]
            disabled = True
            placeholder = "請先選擇遊戲"
        elif not groups:
            options = [discord.SelectOption(label="這個遊戲目前沒有可用計時玩法", value="no_gameplay")]
            disabled = True
            placeholder = "沒有可用玩法"
        else:
            options = [
                discord.SelectOption(
                    label=str(group["label"])[:100],
                    value=str(group["key"])[:100],
                    description="選完後顯示可用的陪玩形式",
                    default=str(group["key"]) == selected_key,
                )
                for group in chunk
            ]
            if page > 1:
                options.append(discord.SelectOption(label="← 上一頁", value=f"page:{page - 1}"))
            if page < total_pages:
                options.append(discord.SelectOption(label="下一頁 →", value=f"page:{page + 1}"))
            disabled = False
            placeholder = "選擇玩法" if total_pages == 1 else f"選擇玩法｜{page}/{total_pages}"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_gameplay_select",
            row=2,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        value = str((self.values or [""])[0])
        if value in {"need_game", "no_gameplay", ""}:
            await interaction.response.defer()
            return

        from services import order_runtime
        from services import vip_timer_select_flow as flow

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})

        if value.startswith("page:"):
            try:
                data["vip_timer_spec_page"] = max(1, int(value.split(":", 1)[1]))
            except (TypeError, ValueError):
                data["vip_timer_spec_page"] = 1
            data.pop("vip_timer_spec_key", None)
            data.pop("vip_timer_spec_label", None)
            _clear_final_selection(data)
        else:
            group = next(
                (row for row in _spec_groups(flow._details_for_game(str(data.get("item_group") or ""))) if row["key"] == value),
                None,
            )
            if group is None:
                await interaction.response.send_message("玩法選項已更新，請重新選擇。", ephemeral=True)
                return
            data["vip_timer_spec_key"] = value
            data["vip_timer_spec_label"] = str(group["label"])
            _clear_final_selection(data)

        state.remember_order(self.channel_id, data)
        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


class VipTimerServiceSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui
        from services import vip_timer_select_flow as flow

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        group = _selected_spec_group(data)
        selected_value = str(data.get("item_detail_value") or "")

        if group is None:
            options = [discord.SelectOption(label="請先選擇玩法", value="need_gameplay")]
            disabled = True
            placeholder = "請先選擇玩法"
        else:
            details = list(group.get("details") or [])
            if not details:
                options = [discord.SelectOption(label="這個玩法目前沒有可用陪玩形式", value="no_service")]
                disabled = True
                placeholder = "沒有可用陪玩形式"
            else:
                options = []
                for detail in details[:25]:
                    service_type = str(detail.get("vip_timer_service_type") or "其他")
                    rate = flow._effective_rate(detail)
                    options.append(
                        discord.SelectOption(
                            label=service_type[:100],
                            value=str(detail.get("value") or "")[:100],
                            description=(f"{rate:,}T / H" if rate > 0 else "開始前重新驗證")[:100],
                            default=str(detail.get("value") or "") == selected_value,
                        )
                    )
                disabled = False
                placeholder = "選擇陪玩形式"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_service_select",
            row=3,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected_value = str((self.values or [""])[0])
        if selected_value in {"need_gameplay", "no_service", ""}:
            await interaction.response.defer()
            return

        from services import order_runtime
        from services.self_service_selection_state import apply_self_service_detail_selection

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        group = _selected_spec_group(data)
        detail = next(
            (row for row in list((group or {}).get("details") or []) if str(row.get("value") or "") == selected_value),
            None,
        )
        if detail is None:
            await interaction.response.send_message("陪玩形式已更新，請重新選擇。", ephemeral=True)
            return

        apply_self_service_detail_selection(data, detail)
        data["quantity"] = 1
        data["vip_timer_order"] = True
        data["vip_timer_service_type"] = str(detail.get("vip_timer_service_type") or "其他")
        state.remember_order(self.channel_id, data)

        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


def _build_embed(customer_id: int, data: dict, guild: discord.Guild | None = None) -> discord.Embed:
    from services import orders
    from services import vip_timer_select_flow as flow

    game = str(data.get("item_group") or "尚未選擇")
    gameplay = str(data.get("vip_timer_spec_label") or "尚未選擇")
    detail = orders.get_order_item_detail_for_selection(
        flow.VIP_TIMER_CATEGORY,
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    service_type = str((detail or {}).get("vip_timer_service_type") or data.get("vip_timer_service_type") or "尚未選擇")

    embed = discord.Embed(
        title="自助下單｜VIP 自由計時",
        description=(
            f"下單用戶：<@{int(customer_id)}>\n\n"
            "金級會員以上限定。先選遊戲與玩法，再依該玩法選可用陪玩形式；接滿後在票口開始計時。\n"
            "不預選時數，中途可切換遊戲／玩法，結束後依實際計時金額付款。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="第一欄｜類型", value="VIP 自由計時", inline=True)
    embed.add_field(name="第二欄｜遊戲", value=game, inline=True)
    embed.add_field(name="第三欄｜玩法", value=gameplay, inline=True)
    embed.add_field(name="第四欄｜陪玩形式", value=service_type, inline=True)
    embed.add_field(name="時間", value="自由計時｜不預選時數", inline=True)

    if detail:
        rate = flow._effective_rate(detail)
        embed.add_field(name="起始參考時薪", value=(f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"), inline=True)
        embed.add_field(name="付款", value="結束計時後付款", inline=True)

    embed.set_footer(text="VIP 自由計時｜上一層會動態限制下一層可選項目")
    return embed


def _install_state_reset_patch() -> None:
    from services import order_runtime
    from services import self_service_selection_state as selection

    category_original = selection.apply_self_service_category_selection
    item_original = selection.apply_self_service_item_group_selection

    def category_state(data: dict, category: str) -> None:
        category_original(data, category)
        for key in ("vip_timer_spec_key", "vip_timer_spec_label", "vip_timer_spec_page"):
            data.pop(key, None)

    def item_group_state(data: dict, selected_group: str):
        result = item_original(data, selected_group)
        for key in ("vip_timer_spec_key", "vip_timer_spec_label", "vip_timer_spec_page"):
            data.pop(key, None)
        return result

    selection.apply_self_service_category_selection = category_state
    order_runtime.apply_self_service_category_selection = category_state
    selection.apply_self_service_item_group_selection = item_group_state
    order_runtime.apply_self_service_item_group_selection = item_group_state


def install_vip_timer_selector_order_v2() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge

    flow._SERVICE_ORDER.clear()
    flow._SERVICE_ORDER.update(
        {
            "單陪": 0,
            "雙陪": 1,
            "三陪": 2,
            "四陪": 3,
            "五陪": 4,
            "六陪": 5,
            "七陪": 6,
            "八陪": 7,
            "甜蜜陪": 20,
            "教學單": 21,
            "其他": 99,
        }
    )
    flow._service_type = _service_type
    flow._spec_label = _spec_label
    flow.VipTimerServiceTypeSelect = VipTimerGameplaySelect
    flow.VipTimerRuleSelect = VipTimerServiceSelect
    flow.build_vip_timer_self_service_panel_embed = _build_embed
    bridge.build_vip_timer_self_service_panel_embed = _build_embed

    flow._CATALOG_CACHE = None
    flow._CATALOG_CACHE_AT = 0.0
    flow.refresh_vip_timer_self_service_catalog()
    _install_state_reset_patch()
    _INSTALLED = True


__all__ = [
    "VipTimerGameplaySelect",
    "VipTimerServiceSelect",
    "install_vip_timer_selector_order_v2",
]
