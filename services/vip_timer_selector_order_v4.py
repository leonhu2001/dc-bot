from __future__ import annotations

import discord


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None
_ORIGINAL_SPEC_GROUPS = None


def _direct_details_for_game(game_label: str | None) -> list[dict]:
    """Read VIP timer rows by their real second-layer game label.

    The generic storefront helper intentionally honors ``catalog_group_label``.
    That is correct for normal checkout, but it turns the VIP timer's game layer
    back into gameplay groups (娛樂陪／技術陪/...). VIP timer therefore reads its
    own generated catalog directly.
    """
    if not game_label:
        return []

    from services import orders
    from services import vip_timer_select_flow as flow

    for group in list(orders.SELF_SERVICE_ORDER_CATALOG.get(flow.VIP_TIMER_CATEGORY, ()) or ()):
        if str(group.get("label") or "").strip() == str(game_label).strip():
            return [dict(row) for row in list(group.get("details") or ())]
    return []


def _rule_group_label(detail: dict) -> str:
    from services.order_rules import ORDER_RULES

    rule = ORDER_RULES.get(str(detail.get("rule_key") or "").strip())
    if rule is None:
        return ""
    return str(getattr(rule, "catalog_group_label", "") or "").strip()


def _semantic_family(detail: dict) -> str:
    """Keep distinct gameplay products apart before grouping by headcount.

    Several Delta products intentionally share the same spec label (for example
    技術｜機密), but they are not the same gameplay: ordinary 技術陪 and
    一陪一護 have different staffing and payout rules. Grouping by spec first can
    therefore silently replace one product with the other. Prefer the product's
    explicit catalog group whenever present; otherwise derive a stable gameplay
    family from the VIP spec label.
    """
    explicit = _rule_group_label(detail)
    if explicit:
        return f"group:{explicit}"

    spec = str(detail.get("vip_timer_spec_label") or "").strip()
    item = str(detail.get("item") or detail.get("label") or "").strip()
    text = f"{spec}｜{item}"

    if "絕巴技術陪" in text:
        return "builtin:絕巴技術陪"
    if "黑潮" in text:
        return "builtin:黑潮爆破"
    if "娛樂" in text:
        return "builtin:娛樂陪"
    if "甜蜜" in text:
        return "builtin:甜蜜"
    if "教學" in text or "導師" in text:
        return "builtin:教學"
    if "技術" in text:
        return "builtin:技術陪"

    head = spec.split("｜", 1)[0].strip() if spec else "其他"
    return f"builtin:{head or '其他'}"


def _display_gameplay_label(group: dict) -> str:
    details = list(group.get("details") or ())
    original = str(group.get("label") or "玩法").strip() or "玩法"
    bases = [
        _rule_group_label(row)
        for row in details
        if _rule_group_label(row)
    ]
    base = bases[0] if bases and all(value == bases[0] for value in bases) else ""

    if not base:
        if original == "娛樂":
            return "娛樂陪"
        if original == "技術":
            return "技術陪"
        if original.startswith("技術｜"):
            return f"技術陪｜{original.split('｜', 1)[1]}"[:100]
        return original[:100]

    # Keep the familiar storefront group name. When one group has multiple
    # materially different price/spec variants (e.g. 技術陪 機密/絕密), preserve
    # the qualifier so the fourth layer can remain purely headcount without
    # silently choosing the wrong price.
    if original in {"娛樂", "甜蜜", "教學", base}:
        return base[:100]
    if original.startswith("技術｜"):
        qualifier = original.split("｜", 1)[1].strip()
        if qualifier and qualifier not in base:
            return f"{base}｜{qualifier}"[:100]
        return base[:100]
    if original in base or base in original:
        return base[:100]
    return f"{base}｜{original}"[:100]


def _gameplay_groups(details: list[dict]) -> list[dict]:
    if _ORIGINAL_SPEC_GROUPS is None:
        return []

    # Split by semantic gameplay family *before* v3 collapses equal spec labels.
    # This prevents ordinary 技術陪 and 一陪一護 from competing for the same
    # 單陪/雙陪 slot simply because both happen to use 機密／絕密 wording.
    family_rows: dict[str, list[dict]] = {}
    family_order: list[str] = []
    for detail in list(details or ()):
        family = _semantic_family(detail)
        if family not in family_rows:
            family_rows[family] = []
            family_order.append(family)
        family_rows[family].append(detail)

    rows: list[dict] = []
    seen_keys: set[str] = set()
    for family in family_order:
        for raw_group in list(_ORIGINAL_SPEC_GROUPS(family_rows[family]) or ()):
            group = dict(raw_group)
            display = _display_gameplay_label(group)
            group["label"] = display
            # v2 uses the group key as the select value. Make it family-aware so
            # two distinct gameplay families can never collide on Discord.
            group["key"] = f"{family}:{str(group.get('key') or display)}"[:100]
            if group["key"] in seen_keys:
                continue
            seen_keys.add(group["key"])
            rows.append(group)

    # Keep the pre-existing gameplay ordering from v3/v5 after the family split.
    try:
        from services import vip_timer_selector_order_v3 as v3

        rows.sort(key=v3._group_sort_key)
    except Exception:
        pass
    return rows


def _game_rows() -> list[dict]:
    from services import orders
    from services import vip_timer_select_flow as flow

    flow.refresh_vip_timer_self_service_catalog()
    return [
        dict(group)
        for group in list(orders.SELF_SERVICE_ORDER_CATALOG.get(flow.VIP_TIMER_CATEGORY, ()) or ())
        if str(group.get("label") or "").strip()
        and list(group.get("details") or ())
    ]


def _clear_after_game_change(data: dict, game_label: str) -> None:
    from services.self_service_selection_state import clear_product_dependent_selection_state

    data["item_group"] = str(game_label)
    for key in (
        "item_detail_value",
        "item",
        "order_rule_key",
        "player_count",
        "specified_staff_ids",
        "payment_method",
        "vip_timer_spec_key",
        "vip_timer_spec_label",
        "vip_timer_spec_page",
        "vip_timer_service_type",
        "vip_timer_service_page",
        "vip_timer_service_game",
    ):
        data.pop(key, None)
    clear_product_dependent_selection_state(data)
    data["quantity"] = 1
    data["companion_preference"] = "不指定陪玩/打手"
    data["vip_timer_order"] = True


def _can_operate(interaction: discord.Interaction, customer_id: int) -> bool:
    from core.permissions import can_operate_self_service_order

    return bool(can_operate_self_service_order(interaction.user, customer_id))


class VipTimerGameSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        selected = str(data.get("item_group") or "")
        rows = _game_rows()
        options = [
            discord.SelectOption(
                label=str(group.get("label") or "遊戲")[:100],
                value=str(group.get("label") or "")[:100],
                description="選完後第三欄只顯示這個遊戲可用的玩法"[:100],
                default=str(group.get("label") or "") == selected,
            )
            for group in rows[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="目前沒有可用的計時遊戲", value="__none__")]

        super().__init__(
            placeholder="選擇遊戲",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_game_select",
            row=1,
            disabled=(not rows),
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected = str((self.values or [""])[0])
        if selected in {"", "__none__"}:
            await interaction.response.defer()
            return

        valid_games = {str(group.get("label") or "") for group in _game_rows()}
        if selected not in valid_games:
            await interaction.response.send_message("遊戲清單已更新，請重新選擇。", ephemeral=True)
            return

        from services import order_runtime

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        _clear_after_game_change(data, selected)
        state.remember_order(self.channel_id, data)

        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


def _selected_detail(data: dict) -> dict | None:
    selected = str(data.get("item_detail_value") or "")
    if not selected:
        return None
    return next(
        (
            row
            for row in _direct_details_for_game(str(data.get("item_group") or ""))
            if str(row.get("value") or "") == selected
        ),
        None,
    )


def _build_embed(customer_id: int, data: dict, guild: discord.Guild | None = None) -> discord.Embed:
    from services import vip_timer_select_flow as flow

    game = str(data.get("item_group") or "尚未選擇")
    gameplay = str(data.get("vip_timer_spec_label") or "尚未選擇")
    detail = _selected_detail(data)
    headcount = str(
        (detail or {}).get("vip_timer_service_type")
        or data.get("vip_timer_service_type")
        or "尚未選擇"
    )

    embed = discord.Embed(
        title="自助下單｜VIP 自由計時",
        description=(
            f"下單用戶：<@{int(customer_id)}>\n\n"
            "金級會員以上限定。依序選擇遊戲 → 玩法 → 陪玩人數；接滿後在票口開始計時。\n"
            "不預選時數，中途可切換遊戲／玩法，結束後依實際計時金額付款。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="第一欄｜類型", value="VIP 自由計時", inline=True)
    embed.add_field(name="第二欄｜遊戲", value=game, inline=True)
    embed.add_field(name="第三欄｜玩法", value=gameplay, inline=True)
    embed.add_field(name="第四欄｜陪玩人數", value=headcount, inline=True)
    embed.add_field(name="時間", value="自由計時｜不預選時數", inline=True)

    if detail:
        rate = int(flow._effective_rate(detail) or 0)
        embed.add_field(
            name="起始參考時薪",
            value=(f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"),
            inline=True,
        )
        embed.add_field(name="付款", value="結束計時後付款", inline=True)

    embed.set_footer(text="VIP 自由計時｜遊戲會動態限制玩法，玩法會動態限制可選陪玩人數")
    return embed


def _install_view_patch() -> None:
    global _ORIGINAL_VIEW_INIT

    from services import self_service_ui_runtime as ui
    from services import vip_timer_select_flow as flow
    from services import vip_timer_selector_order_v2 as v2

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def game_first_view_init(view, customer_id: int, channel_id: int, selected_category: str | None = None):
        original(view, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = str(selected_category or data.get("category") or "")
        if category != flow.VIP_TIMER_CATEGORY:
            return

        replace_ids = {
            "self_service_order_item_select",
            "self_service_order_detail_select",
            "self_service_order_quantity_select",
            "vip_timer_service_type_select",
            "vip_timer_rule_select",
            "vip_timer_gameplay_select",
            "vip_timer_service_select",
            "vip_timer_game_select",
        }
        for child in list(view.children):
            if str(getattr(child, "custom_id", "") or "") in replace_ids:
                view.remove_item(child)

        view.add_item(VipTimerGameSelect(customer_id, channel_id))
        view.add_item(v2.VipTimerGameplaySelect(customer_id, channel_id))
        view.add_item(v2.VipTimerServiceSelect(customer_id, channel_id))

    ui.SelfServiceOrderView.__init__ = game_first_view_init


def install_vip_timer_selector_order_v4() -> None:
    """Make checkout exactly category -> game -> gameplay -> headcount."""
    global _INSTALLED, _ORIGINAL_SPEC_GROUPS
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge
    from services import vip_timer_selector_order_v2 as v2
    from services import vip_timer_selector_order_v3 as v3

    if _ORIGINAL_SPEC_GROUPS is None:
        _ORIGINAL_SPEC_GROUPS = v3._spec_groups

    flow._details_for_game = _direct_details_for_game
    v2._spec_groups = _gameplay_groups
    v3._spec_groups = _gameplay_groups
    flow.build_vip_timer_self_service_panel_embed = _build_embed
    bridge.build_vip_timer_self_service_panel_embed = _build_embed

    _install_view_patch()
    _INSTALLED = True


__all__ = [
    "VipTimerGameSelect",
    "install_vip_timer_selector_order_v4",
]
