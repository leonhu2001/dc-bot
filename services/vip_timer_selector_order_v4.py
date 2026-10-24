from __future__ import annotations

import hashlib
import re

import discord


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None
_HEADCOUNT_ORDER = {
    "單陪": 0,
    "雙陪": 1,
    "三陪": 2,
    "四陪": 3,
    "五陪": 4,
    "六陪": 5,
    "七陪": 6,
    "八陪": 7,
    "九陪": 8,
    "女單陪": 0,
    "男單陪": 1,
    "女雙陪": 2,
    "男雙陪": 3,
    "1對1教學": 0,
}


def _direct_details_for_game(game_label: str | None) -> list[dict]:
    """Read VIP timer rows by their real game label, never storefront groups."""
    if not game_label:
        return []

    from services import orders
    from services import vip_timer_select_flow as flow

    for group in list(
        orders.SELF_SERVICE_ORDER_CATALOG.get(flow.VIP_TIMER_CATEGORY, ()) or ()
    ):
        if str(group.get("label") or "").strip() == str(game_label).strip():
            return [dict(row) for row in list(group.get("details") or ())]
    return []


def _rule_for_detail(detail: dict):
    from services.order_rules import ORDER_RULES

    return ORDER_RULES.get(str(detail.get("rule_key") or "").strip())


def _rule_group_label(detail: dict) -> str:
    rule = _rule_for_detail(detail)
    if rule is None:
        return ""
    return str(getattr(rule, "catalog_group_label", "") or "").strip()


def _stable_key(prefix: str, label: str) -> str:
    digest = hashlib.sha1(str(label).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _strip_headcount_words(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"(?:｜?陪玩[1-9]名)", "", value)
    value = re.sub(
        r"(?:女單陪|男單陪|女雙陪|男雙陪|單陪|雙陪|三陪|四陪|五陪|六陪|七陪|八陪|九陪|[1-9]陪)",
        "",
        value,
    )
    return value.strip("｜ /-")


def _classification_label(detail: dict) -> str:
    """Return the storefront-style category shown before concrete gameplay."""
    explicit = _rule_group_label(detail)
    if explicit and explicit not in {"後台新增商品", "其他"}:
        return _strip_headcount_words(explicit)[:100]

    spec = str(detail.get("vip_timer_spec_label") or "")
    item = str(detail.get("item") or detail.get("label") or "")
    text = f"{explicit}｜{spec}｜{item}"

    for special in ("絕巴技術陪", "黑潮爆破", "一陪一護"):
        if special in text:
            return special
    if "娛樂" in text:
        return "娛樂陪"
    if "甜蜜" in text:
        return "甜蜜陪"
    if "教學" in text or "導師" in text:
        return "教學"
    if "技術" in text:
        return "技術陪"

    clean = _strip_headcount_words(explicit or item or spec)
    if "｜" in clean:
        clean = clean.split("｜", 1)[0].strip()
    return (clean or "其他")[:100]


def _remove_classification_words(text: str, classification: str) -> str:
    value = _strip_headcount_words(text)
    tokens = {
        str(classification or "").strip(),
        str(classification or "").replace("陪", "").strip(),
    }
    if "技術" in classification:
        tokens.update({"技術", "技術陪", "技術單"})
    if "娛樂" in classification:
        tokens.update({"娛樂", "娛樂陪"})
    if "甜蜜" in classification:
        tokens.update({"甜蜜", "甜蜜陪", "甜蜜單"})
    if "教學" in classification:
        tokens.update({"教學", "教學單", "導師"})

    parts = []
    for raw in re.split(r"[｜/]+", value):
        part = raw.strip()
        if not part or part in tokens:
            continue
        cleaned = part
        for token in sorted(tokens, key=len, reverse=True):
            if token:
                cleaned = cleaned.replace(token, "").strip(" ｜/-")
        if cleaned and cleaned not in {"一般", "基礎"}:
            parts.append(cleaned)
    return "｜".join(dict.fromkeys(parts)).strip("｜ ")


def _gameplay_label(detail: dict, classification: str) -> str:
    """Return the concrete mode/spec inside one category.

    Examples: 技術陪 -> 機密/絕密, 英雄聯盟娛樂陪 -> ARAM/NG/積分.
    """
    candidates = (
        str(detail.get("vip_timer_spec_label") or ""),
        str(detail.get("label") or ""),
        str(detail.get("item") or ""),
    )
    for candidate in candidates:
        cleaned = _remove_classification_words(candidate, classification)
        if cleaned and cleaned not in {"娛樂", "技術", "甜蜜", "教學"}:
            return cleaned[:100]
    return "一般"


def _effective_rate(detail: dict) -> int:
    from services import vip_timer_select_flow as flow

    return int(flow._effective_rate(detail) or 0)


def _category_sort_key(group: dict) -> tuple:
    label = str(group.get("label") or "")
    if label == "娛樂陪":
        family = 0
    elif label == "技術陪":
        family = 10
    elif label == "絕巴技術陪":
        family = 20
    elif label == "黑潮爆破":
        family = 30
    elif label == "甜蜜陪":
        family = 40
    elif label == "教學":
        family = 50
    else:
        family = 15
    return (family, int(group.get("min_rate") or 0), label)


def _gameplay_sort_key(group: dict) -> tuple:
    label = str(group.get("label") or "")
    known = {
        "一般": 0,
        "ARAM": 5,
        "NG": 10,
        "積分": 20,
        "機密": 30,
        "絕密": 40,
        "絕巴": 50,
    }.get(label, 100)
    return (known, int(group.get("min_rate") or 0), label)


def _category_groups(details: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for detail in list(details or ()):
        label = _classification_label(detail)
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label, rows in grouped.items():
        rates = [_effective_rate(row) for row in rows if _effective_rate(row) > 0]
        result.append(
            {
                "key": _stable_key("cat", label),
                "label": label[:100],
                "details": rows,
                "min_rate": min(rates) if rates else 0,
            }
        )
    result.sort(key=_category_sort_key)
    return result


def _gameplay_groups(details: list[dict], classification: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for detail in list(details or ()):
        label = _gameplay_label(detail, classification)
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label, rows in grouped.items():
        rates = [_effective_rate(row) for row in rows if _effective_rate(row) > 0]
        result.append(
            {
                "key": _stable_key("play", f"{classification}|{label}"),
                "label": label[:100],
                "details": rows,
                "min_rate": min(rates) if rates else 0,
            }
        )
    result.sort(key=_gameplay_sort_key)
    return result


def _game_rows() -> list[dict]:
    from services import orders
    from services import vip_timer_select_flow as flow

    flow.refresh_vip_timer_self_service_catalog()
    return [
        dict(group)
        for group in list(
            orders.SELF_SERVICE_ORDER_CATALOG.get(flow.VIP_TIMER_CATEGORY, ()) or ()
        )
        if str(group.get("label") or "").strip()
        and list(group.get("details") or ())
    ]


def _clear_product_selection(data: dict) -> None:
    from services.self_service_selection_state import clear_product_dependent_selection_state

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
    clear_product_dependent_selection_state(data)
    data["quantity"] = 1
    data["companion_preference"] = "不指定陪玩/打手"
    data["vip_timer_order"] = True


def _clear_after_game_change(data: dict, game_label: str) -> None:
    data["item_group"] = str(game_label)
    for key in (
        "vip_timer_category_key",
        "vip_timer_category_label",
        "vip_timer_spec_key",
        "vip_timer_spec_label",
        "vip_timer_spec_page",
    ):
        data.pop(key, None)
    _clear_product_selection(data)


def _clear_after_category_change(data: dict, group: dict) -> None:
    data["vip_timer_category_key"] = str(group.get("key") or "")
    data["vip_timer_category_label"] = str(group.get("label") or "")
    for key in ("vip_timer_spec_key", "vip_timer_spec_label", "vip_timer_spec_page"):
        data.pop(key, None)
    _clear_product_selection(data)


def _clear_after_gameplay_change(data: dict, group: dict) -> None:
    data["vip_timer_spec_key"] = str(group.get("key") or "")
    data["vip_timer_spec_label"] = str(group.get("label") or "")
    data.pop("vip_timer_spec_page", None)
    _clear_product_selection(data)


def _selected_category_group(data: dict) -> dict | None:
    game = str(data.get("item_group") or "")
    selected = str(data.get("vip_timer_category_key") or "")
    if not game or not selected:
        return None
    return next(
        (
            group
            for group in _category_groups(_direct_details_for_game(game))
            if str(group.get("key") or "") == selected
        ),
        None,
    )


def _selected_gameplay_group(data: dict) -> dict | None:
    category = _selected_category_group(data)
    selected = str(data.get("vip_timer_spec_key") or "")
    if category is None or not selected:
        return None
    return next(
        (
            group
            for group in _gameplay_groups(
                list(category.get("details") or ()),
                str(category.get("label") or ""),
            )
            if str(group.get("key") or "") == selected
        ),
        None,
    )


def _detail_preference(detail: dict) -> tuple:
    try:
        from services import vip_timer_selector_order_v3 as v3

        return tuple(v3._detail_preference(detail))
    except Exception:
        return (0, 0, -len(str(detail.get("value") or "")))


def _headcount_label(detail: dict) -> str:
    label = str(detail.get("vip_timer_service_type") or "").strip()
    if label and label != "不支援":
        return label[:100]
    try:
        count = max(1, int(detail.get("player_count") or 1))
    except (TypeError, ValueError):
        count = 1
    chinese = {
        1: "單陪",
        2: "雙陪",
        3: "三陪",
        4: "四陪",
        5: "五陪",
        6: "六陪",
        7: "七陪",
        8: "八陪",
        9: "九陪",
    }
    return chinese.get(count, f"{count}陪")


def _headcount_details(group: dict | None) -> list[dict]:
    by_label: dict[str, dict] = {}
    for detail in list((group or {}).get("details") or ()):
        label = _headcount_label(detail)
        current = by_label.get(label)
        if current is None or _detail_preference(detail) > _detail_preference(current):
            by_label[label] = detail
    rows = list(by_label.values())
    rows.sort(
        key=lambda row: (
            _HEADCOUNT_ORDER.get(_headcount_label(row), 99),
            _headcount_label(row),
            _effective_rate(row),
        )
    )
    return rows


def _selected_detail(data: dict) -> dict | None:
    selected = str(data.get("item_detail_value") or "")
    if not selected:
        return None
    group = _selected_gameplay_group(data)
    return next(
        (
            row
            for row in list((group or {}).get("details") or ())
            if str(row.get("value") or "") == selected
        ),
        None,
    )


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
                description="先選遊戲，再選這個遊戲的分類"[:100],
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
            row=0,
            disabled=(not rows),
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有開這張票口的用戶或客服可以選擇訂單。",
                ephemeral=True,
            )
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


class VipTimerCategorySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        game = str(data.get("item_group") or "")
        groups = _category_groups(_direct_details_for_game(game)) if game else []
        selected_key = str(data.get("vip_timer_category_key") or "")

        if not game:
            options = [discord.SelectOption(label="請先選擇遊戲", value="need_game")]
            disabled = True
            placeholder = "請先選擇遊戲"
        elif not groups:
            options = [discord.SelectOption(label="這個遊戲目前沒有可用分類", value="no_category")]
            disabled = True
            placeholder = "沒有可用分類"
        else:
            options = [
                discord.SelectOption(
                    label=str(group.get("label") or "分類")[:100],
                    value=str(group.get("key") or "")[:100],
                    description="選完後再選該分類的玩法／規格"[:100],
                    default=str(group.get("key") or "") == selected_key,
                )
                for group in groups[:25]
            ]
            disabled = False
            placeholder = "選擇分類"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_category_select",
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有開這張票口的用戶或客服可以選擇訂單。",
                ephemeral=True,
            )
            return

        value = str((self.values or [""])[0])
        if value in {"", "need_game", "no_category"}:
            await interaction.response.defer()
            return

        from services import order_runtime

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        group = next(
            (
                row
                for row in _category_groups(
                    _direct_details_for_game(str(data.get("item_group") or ""))
                )
                if str(row.get("key") or "") == value
            ),
            None,
        )
        if group is None:
            await interaction.response.send_message("分類清單已更新，請重新選擇。", ephemeral=True)
            return

        _clear_after_category_change(data, group)
        state.remember_order(self.channel_id, data)
        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


class VipTimerGameplaySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = _selected_category_group(data)
        groups = (
            _gameplay_groups(
                list(category.get("details") or ()),
                str(category.get("label") or ""),
            )
            if category is not None
            else []
        )
        selected_key = str(data.get("vip_timer_spec_key") or "")

        if category is None:
            options = [discord.SelectOption(label="請先選擇分類", value="need_category")]
            disabled = True
            placeholder = "請先選擇分類"
        elif not groups:
            options = [discord.SelectOption(label="這個分類目前沒有可用玩法", value="no_gameplay")]
            disabled = True
            placeholder = "沒有可用玩法"
        else:
            options = [
                discord.SelectOption(
                    label=str(group.get("label") or "玩法")[:100],
                    value=str(group.get("key") or "")[:100],
                    description="選完後再選陪玩人數"[:100],
                    default=str(group.get("key") or "") == selected_key,
                )
                for group in groups[:25]
            ]
            disabled = False
            placeholder = "選擇玩法／規格"

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
            await interaction.response.send_message(
                "只有開這張票口的用戶或客服可以選擇訂單。",
                ephemeral=True,
            )
            return

        value = str((self.values or [""])[0])
        if value in {"", "need_category", "no_gameplay"}:
            await interaction.response.defer()
            return

        from services import order_runtime

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        category = _selected_category_group(data)
        groups = (
            _gameplay_groups(
                list(category.get("details") or ()),
                str(category.get("label") or ""),
            )
            if category is not None
            else []
        )
        group = next(
            (row for row in groups if str(row.get("key") or "") == value),
            None,
        )
        if group is None:
            await interaction.response.send_message("玩法清單已更新，請重新選擇。", ephemeral=True)
            return

        _clear_after_gameplay_change(data, group)
        state.remember_order(self.channel_id, data)
        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


class VipTimerHeadcountSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)

        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        gameplay = _selected_gameplay_group(data)
        details = _headcount_details(gameplay)
        selected_value = str(data.get("item_detail_value") or "")

        if gameplay is None:
            options = [discord.SelectOption(label="請先選擇玩法／規格", value="need_gameplay")]
            disabled = True
            placeholder = "請先選擇玩法／規格"
        elif not details:
            options = [discord.SelectOption(label="這個玩法目前沒有可用人數", value="no_headcount")]
            disabled = True
            placeholder = "沒有可用陪玩人數"
        else:
            options = [
                discord.SelectOption(
                    label=_headcount_label(detail)[:100],
                    value=str(detail.get("value") or "")[:100],
                    description=(
                        f"{_effective_rate(detail):,}T / H"
                        if _effective_rate(detail) > 0
                        else "開始前重新驗證"
                    )[:100],
                    default=str(detail.get("value") or "") == selected_value,
                )
                for detail in details[:25]
            ]
            disabled = False
            placeholder = "選擇陪玩人數"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vip_timer_headcount_select",
            row=3,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_operate(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有開這張票口的用戶或客服可以選擇訂單。",
                ephemeral=True,
            )
            return

        selected_value = str((self.values or [""])[0])
        if selected_value in {"", "need_gameplay", "no_headcount"}:
            await interaction.response.defer()
            return

        from services import order_runtime
        from services.self_service_selection_state import apply_self_service_detail_selection

        state = order_runtime._require_runtime_state()
        data = state.order_selections.setdefault(self.channel_id, {})
        gameplay = _selected_gameplay_group(data)
        detail = next(
            (
                row
                for row in _headcount_details(gameplay)
                if str(row.get("value") or "") == selected_value
            ),
            None,
        )
        if detail is None:
            await interaction.response.send_message("陪玩人數已更新，請重新選擇。", ephemeral=True)
            return

        apply_self_service_detail_selection(data, detail)
        data["quantity"] = 1
        data["vip_timer_order"] = True
        data["vip_timer_service_type"] = _headcount_label(detail)
        state.remember_order(self.channel_id, data)
        await state.defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )


def _build_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    game = str(data.get("item_group") or "尚未選擇")
    category = str(data.get("vip_timer_category_label") or "尚未選擇")
    gameplay = str(data.get("vip_timer_spec_label") or "尚未選擇")
    detail = _selected_detail(data)
    headcount = _headcount_label(detail) if detail else "尚未選擇"

    embed = discord.Embed(
        title="自助下單｜VIP 自由計時",
        description=(
            f"下單用戶：<@{int(customer_id)}>\n\n"
            "依序選擇遊戲 → 分類 → 玩法／規格 → 陪玩人數；接滿後在票口開始計時。\n"
            "不預選時數，中途可切換遊戲／玩法，結束後依實際計時金額付款。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="第一欄｜類型", value="VIP 自由計時", inline=True)
    embed.add_field(name="第二欄｜遊戲", value=game, inline=True)
    embed.add_field(name="第三欄｜分類", value=category, inline=True)
    embed.add_field(name="第四欄｜玩法／規格", value=gameplay, inline=True)
    embed.add_field(name="第五欄｜陪玩人數", value=headcount, inline=True)
    embed.add_field(name="時間", value="自由計時｜不預選時數", inline=True)

    if detail:
        rate = _effective_rate(detail)
        embed.add_field(
            name="起始參考時薪",
            value=(f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"),
            inline=True,
        )
        embed.add_field(name="付款", value="結束計時後付款", inline=True)

    embed.set_footer(text="VIP 自由計時｜先選分類，再選該分類內的玩法與陪玩人數")
    return embed


def _install_view_patch() -> None:
    global _ORIGINAL_VIEW_INIT

    from services import self_service_ui_runtime as ui
    from services import vip_timer_select_flow as flow

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def category_first_view_init(
        view,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
    ):
        original(view, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = str(selected_category or data.get("category") or "")
        if category != flow.VIP_TIMER_CATEGORY:
            return

        replace_ids = {
            "self_service_order_category_select",
            "self_service_order_item_select",
            "self_service_order_detail_select",
            "self_service_order_quantity_select",
            "vip_timer_service_type_select",
            "vip_timer_rule_select",
            "vip_timer_gameplay_select",
            "vip_timer_service_select",
            "vip_timer_game_select",
            "vip_timer_category_select",
            "vip_timer_headcount_select",
        }
        remove_timer_buttons = {
            "self_service_order_specified_staff_button",
            "self_service_order_point_benefit_button",
            "self_service_order_staff_price_button",
            "self_service_order_staff_discount_coupon_button",
        }
        for child in list(view.children):
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id in replace_ids or custom_id in remove_timer_buttons:
                view.remove_item(child)

        view.add_item(VipTimerGameSelect(customer_id, channel_id))
        view.add_item(VipTimerCategorySelect(customer_id, channel_id))
        view.add_item(VipTimerGameplaySelect(customer_id, channel_id))
        view.add_item(VipTimerHeadcountSelect(customer_id, channel_id))

    ui.SelfServiceOrderView.__init__ = category_first_view_init


def install_vip_timer_selector_order_v4() -> None:
    """Use timer category -> game -> category -> gameplay/spec -> headcount."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge

    flow._details_for_game = _direct_details_for_game
    flow.build_vip_timer_self_service_panel_embed = _build_embed
    bridge.build_vip_timer_self_service_panel_embed = _build_embed

    _install_view_patch()
    _INSTALLED = True


__all__ = [
    "VipTimerCategorySelect",
    "VipTimerGameSelect",
    "VipTimerGameplaySelect",
    "VipTimerHeadcountSelect",
    "install_vip_timer_selector_order_v4",
]
