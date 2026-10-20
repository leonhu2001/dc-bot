from __future__ import annotations

from dataclasses import replace
from typing import Any

import discord
from sqlalchemy import text

from services.vip_timer import (
    VIP_TIMER_CATEGORY,
    VIP_TIMER_CATEGORY_LABEL,
    VIP_TIMER_MARKER,
    create_vip_timer_session,
    has_open_vip_timer,
)
from services.vip_timer_catalog_guard import is_public_timer_rule


_INSTALLED = False
_ORIGINAL_CATEGORY_CALLBACK = None
_ORIGINAL_VIEW_INIT = None
_ORIGINAL_PANEL_BUILDER = None
_ORIGINAL_CATEGORY_STATE_APPLIER = None
_ORIGINAL_WAITING_ORDER_CREATOR = None

_GOLD_OR_ABOVE = {
    "金級魔丸",
    "白金魔丸",
    "鑽石魔丸",
    "白鑽魔丸",
    "黑鑽魔丸",
}

_GAME_LABELS = {
    "delta_desktop_basic": "三角洲行動｜端遊",
    "delta_mobile_basic": "三角洲行動｜手遊",
    "delta_desktop_fun": "三角洲行動｜趣味",
    "steam": "STEAM 遊戲",
    "valorant": "特戰英豪",
    "lol": "英雄聯盟",
    "apex": "APEX",
    "custom": "其他／自訂",
}

_TIMER_DRAFT_CLEAR_KEYS = (
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
    "point_free_first_hour_amount",
    "point_extra_hours",
    "point_extra_games",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_discount_amount",
    "benefit_service_note",
    "manual_discount_mode",
    "manual_discount_percent",
    "manual_discount_percent_override",
    "manual_discount_reason",
    "cash_coupon_amount",
    "fixed_discount_amount",
    "cash_coupon_reason",
    "manual_staff_amount",
    "manual_staff_price_reason",
    "manual_staff_price_set_by",
    "manual_staff_price_set_at",
    "specified_staff_ids",
    "payment_method",
)

_ZERO_MONEY_KEYS = (
    "service_original_amount",
    "rule_original_amount",
    "original_amount",
    "priced_amount",
    "manual_discount_amount",
    "percent_discount_amount",
    "fixed_discount_amount",
    "payout_base_amount",
    "cash_coupon_amount",
    "point_discount_coupon_amount",
    "vip_monthly_cash_amount",
    "benefit_discount_amount",
    "store_absorbed_amount",
    "customer_pay_amount",
    "amount",
    "total_amount",
    "effective_specify_fee",
    "specified_fee_before_waiver",
    "point_free_first_hour_amount",
    "point_extra_hours",
    "point_extra_games",
)

_CLEAR_BENEFIT_KEYS = (
    "point_benefit_key",
    "point_benefit_name",
    "point_benefit_cost",
    "vip_monthly_benefit_id",
    "vip_monthly_benefit_key",
    "vip_monthly_benefit_title",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_service_note",
    "service_bonus_text",
    "service_promotion_text",
)


def is_vip_timer_self_service_data(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    return bool(data.get("vip_timer_order")) or str(data.get("category") or "") == VIP_TIMER_CATEGORY


def _customer_vip_name(customer_id: int | str) -> str:
    from services.rewards import get_customer_reward_data, get_effective_member_level

    try:
        reward_data = get_customer_reward_data(int(customer_id))
        level = get_effective_member_level(reward_data)
    except Exception:
        return "普通魔丸"
    return str((level or {}).get("name") or "普通魔丸")


def assert_vip_timer_self_service_eligible(
    customer_id: int | str,
    *,
    check_open_order: bool = True,
) -> None:
    if _customer_vip_name(customer_id) not in _GOLD_OR_ABOVE:
        raise ValueError("VIP 自由計時單僅限金級會員以上使用。")
    if check_open_order and has_open_vip_timer(str(customer_id)):
        raise ValueError("你目前已有一張進行中或待付款的 VIP 自由計時單，請先完成上一張。")


def prepare_vip_timer_draft(data: dict) -> None:
    for key in _TIMER_DRAFT_CLEAR_KEYS:
        data.pop(key, None)
    data["category"] = VIP_TIMER_CATEGORY
    data["vip_timer_order"] = True
    data["quantity"] = 1
    data["companion_preference"] = "不指定陪玩/打手"


def zero_vip_timer_financials(raw: dict) -> dict:
    result = dict(raw or {})
    for key in _ZERO_MONEY_KEYS:
        result[key] = 0
    for key in _CLEAR_BENEFIT_KEYS:
        result[key] = None
    result["manual_discount_percent"] = 100
    result["discount_rate_percent"] = 100
    result["manual_discount_reason"] = None
    result["cash_coupon_reason"] = None
    result["manual_staff_amount"] = None
    result["manual_staff_price_reason"] = None
    result["manual_price_missing"] = False
    result["point_waived_specify_fee"] = False
    result["vip_timer"] = True
    return result


def _timer_detail_value(rule_key: str, player_count: int | None) -> str:
    return f"vt:{str(rule_key)}:{int(player_count or 0)}"[:100]


def _timer_game_label(category: str) -> str:
    from services import orders

    return _GAME_LABELS.get(
        str(category),
        str(orders.ORDER_CATEGORY_LABELS.get(str(category), str(category))),
    )


def build_vip_timer_self_service_catalog() -> list[dict]:
    """Build one VIP timer category whose second selector is only the starting game.

    Source products remain canonical. We copy their selectable detail metadata so
    player-count variants still work, then force quantity to one because duration
    is measured by the timer rather than by the normal quantity selector.
    """
    from services import orders
    from services.order_rules import ORDER_RULES

    source_categories = [
        str(category)
        for category in orders.SELF_SERVICE_ACTIVE_CATEGORIES
        if str(category) != VIP_TIMER_CATEGORY
    ]
    grouped: dict[str, list[dict]] = {}
    seen: set[tuple[str, int]] = set()

    for source_category in source_categories:
        game_label = _timer_game_label(source_category)
        for source_group in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(source_category, []):
            for source in orders.get_order_item_details_for_group(source_category, source_group):
                rule_key = str(source.get("rule_key") or "").strip()
                if not rule_key or not is_public_timer_rule(rule_key):
                    continue
                rule = ORDER_RULES.get(rule_key)
                if rule is None:
                    continue
                player_count = source.get("player_count")
                try:
                    player_count_key = int(player_count or 0)
                except (TypeError, ValueError):
                    player_count_key = 0
                unique_key = (rule_key, player_count_key)
                if unique_key in seen:
                    continue
                seen.add(unique_key)

                group_text = str(source_group or "").strip()
                detail_text = str(source.get("label") or getattr(rule, "label", rule_key)).strip()
                label = detail_text
                if group_text and group_text not in detail_text:
                    label = f"{group_text}｜{detail_text}"

                item = dict(source)
                item.update(
                    {
                        "label": label[:100],
                        "value": _timer_detail_value(rule_key, player_count_key),
                        "rule_key": rule_key,
                        "item": str(getattr(rule, "label", rule_key) or rule_key),
                        "quantity_unit": "計時",
                        "min_quantity": 1,
                        "max_quantity": 1,
                        "vip_timer": True,
                        "vip_timer_source_category": source_category,
                    }
                )
                if player_count_key > 0:
                    item["player_count"] = player_count_key
                else:
                    item.pop("player_count", None)
                grouped.setdefault(game_label, []).append(item)

    # Manager-created hourly products can be valid even when they do not have a
    # static self-service detail entry yet. Add them without creating a second
    # source-of-truth price table.
    for rule_key, rule in ORDER_RULES.items():
        key = str(rule_key or "").strip()
        if not key or not is_public_timer_rule(key):
            continue
        represented = any(existing_key == key for existing_key, _ in seen)
        if represented:
            continue

        source_category = str(getattr(rule, "category", "") or "")
        game_label = _timer_game_label(source_category)
        if bool(getattr(rule, "player_count_enabled", False)):
            minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
            maximum_raw = getattr(rule, "max_player_count", None)
            maximum = int(maximum_raw) if maximum_raw is not None else minimum
            counts = range(minimum, min(maximum, 8) + 1)
        else:
            counts = (0,)

        for count in counts:
            unique_key = (key, int(count or 0))
            if unique_key in seen:
                continue
            seen.add(unique_key)
            count_label = f"｜陪玩{count}名" if count else ""
            grouped.setdefault(game_label, []).append(
                {
                    "label": f"{getattr(rule, 'label', key)}{count_label}"[:100],
                    "value": _timer_detail_value(key, int(count or 0)),
                    "rule_key": key,
                    "item": str(getattr(rule, "label", key) or key),
                    "player_count": int(count) if count else None,
                    "quantity_unit": "計時",
                    "min_quantity": 1,
                    "max_quantity": 1,
                    "vip_timer": True,
                    "vip_timer_source_category": source_category,
                }
            )

    result: list[dict] = []
    for game_label in sorted(grouped):
        details = sorted(
            grouped[game_label],
            key=lambda row: (str(row.get("label") or ""), str(row.get("value") or "")),
        )
        # Discord select menus support at most 25 options. If one game grows past
        # that, keep the timer as one category and split only its starting-game
        # page instead of silently hiding valid hourly products.
        for offset in range(0, len(details), 25):
            chunk = details[offset : offset + 25]
            if not chunk:
                continue
            page = offset // 25 + 1
            page_label = game_label if len(details) <= 25 else f"{game_label}｜{page}"
            result.append({"label": page_label[:100], "details": chunk})

    return result


def refresh_vip_timer_self_service_catalog() -> None:
    from services import order_runtime, orders

    orders.ORDER_CATEGORY_LABELS[VIP_TIMER_CATEGORY] = VIP_TIMER_CATEGORY_LABEL
    orders.SELF_SERVICE_ORDER_CATALOG[VIP_TIMER_CATEGORY] = build_vip_timer_self_service_catalog()

    categories = tuple(
        category
        for category in orders.SELF_SERVICE_ACTIVE_CATEGORIES
        if str(category) != VIP_TIMER_CATEGORY
    ) + (VIP_TIMER_CATEGORY,)
    orders.SELF_SERVICE_ACTIVE_CATEGORIES = categories
    order_runtime.SELF_SERVICE_ACTIVE_CATEGORIES = categories
    order_runtime.ORDER_CATEGORY_LABELS[VIP_TIMER_CATEGORY] = VIP_TIMER_CATEGORY_LABEL


def build_vip_timer_self_service_panel_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    from services import orders
    from services.self_service_runtime import _get_rule_from_self_service_data

    refresh_vip_timer_self_service_catalog()
    group_label = str(data.get("item_group") or "尚未選擇")
    detail = orders.get_order_item_detail_for_selection(
        VIP_TIMER_CATEGORY,
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    detail_label = str((detail or {}).get("label") or "尚未選擇")

    embed = discord.Embed(
        title="自助下單｜VIP 自由計時",
        description=(
            f"下單用戶：<@{int(customer_id)}>\n\n"
            "金級會員以上限定。先選擇起始遊戲與玩法；接滿後在票口開始計時。\n"
            "中途可切換遊戲／玩法，系統會自動分段；結束後依實際計時金額付款。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="第一欄｜類型", value="VIP 自由計時", inline=True)
    embed.add_field(name="第二欄｜起始遊戲", value=group_label, inline=True)
    embed.add_field(name="第三欄｜起始玩法", value=detail_label, inline=True)

    if data.get("item"):
        try:
            rule = _get_rule_from_self_service_data(data)
            rate = int(getattr(rule, "price", 0) or 0)
            player_count = max(1, int(data.get("player_count") or 1))
            if bool(getattr(rule, "price_multiply_player_count", False)):
                rate *= player_count
            rate_text = f"{rate:,}T / H" if rate > 0 else "開始前重新驗證"
        except Exception:
            rate_text = "開始前重新驗證"
        embed.add_field(name="起始參考時薪", value=rate_text, inline=True)
        embed.add_field(name="計時數量", value="不預選時數", inline=True)
        embed.add_field(name="付款", value="結束計時後付款", inline=True)
    else:
        embed.add_field(
            name="計費方式",
            value="只計實際遊玩時間；尚未開始前不產生應付金額。",
            inline=False,
        )

    embed.set_footer(text="VIP 自由計時｜起始玩法可在遊玩中切換")
    return embed


def _finalize_timer_web_order(
    *,
    order_id: int,
    customer_id: int,
    initial_rule_key: str,
) -> str:
    from shared.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT note FROM web_orders WHERE id=:order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()
        if row is None:
            raise RuntimeError("VIP 自由計時 WebOrder 不存在。")

        marker = f"{VIP_TIMER_MARKER}｜initial_rule={initial_rule_key}｜先玩後付"
        previous_note = str(row.get("note") or "").strip()
        note = marker if not previous_note else f"{marker}｜{previous_note}"

        from services.order_rules import ORDER_RULES

        rule = ORDER_RULES.get(str(initial_rule_key))
        initial_label = str(getattr(rule, "label", initial_rule_key) or initial_rule_key)
        db.execute(
            text(
                """
                UPDATE web_orders
                SET category=:category,
                    item=:item,
                    amount=0,
                    original_amount=0,
                    payout_base_amount=0,
                    customer_pay_amount=0,
                    manual_discount_amount=0,
                    cash_coupon_amount=0,
                    store_absorbed_amount=0,
                    payment_method='待付款',
                    note=:note,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=:order_id
                """
            ),
            {
                "category": VIP_TIMER_CATEGORY_LABEL,
                "item": f"自由計時｜{initial_label}",
                "note": note,
                "order_id": int(order_id),
            },
        )
        create_vip_timer_session(
            db,
            order_id=int(order_id),
            customer_id=str(customer_id),
            initial_rule_key=str(initial_rule_key),
        )
        db.commit()
        return note
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _delete_timer_session(order_id: int) -> None:
    from shared.db import SessionLocal

    db = SessionLocal()
    try:
        for table in ("vip_timer_events", "vip_timer_segments", "vip_timer_sessions"):
            db.execute(text(f"DELETE FROM {table} WHERE order_id=:order_id"), {"order_id": int(order_id)})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def _create_vip_timer_waiting_order(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
    deps,
):
    global _ORIGINAL_WAITING_ORDER_CREATOR

    data = deps.order_selections.setdefault(channel_id, {})
    assert_vip_timer_self_service_eligible(customer_id, check_open_order=True)
    prepare_vip_timer_draft(data)
    refresh_vip_timer_self_service_catalog()

    rule = deps.get_rule_from_data(data)
    if not is_public_timer_rule(str(getattr(rule, "key", "") or "")):
        raise ValueError("這個玩法目前不能用於 VIP 自由計時，請重新選擇起始玩法。")

    source_category = str(getattr(rule, "category", "") or "")
    initial_rule_key = str(getattr(rule, "key", "") or "")
    selected_game = str(data.get("item_group") or "")
    created_timer_order_id: int | None = None

    original_apply_financials = deps.apply_financials
    original_create_plan = deps.create_dispatch_plan
    original_build_embed = deps.build_order_embed

    def timer_apply_financials(order_data, selected_rule, price_result):
        raw = original_apply_financials(order_data, selected_rule, price_result)
        return zero_vip_timer_financials(raw)

    def timer_add_financial_fields(embed, _adjustment):
        embed.add_field(
            name="VIP 自由計時",
            value="先玩後付｜依票口實際計時區段結算",
            inline=False,
        )
        return embed

    def timer_build_order_embed(*args, **kwargs):
        if "item" in kwargs:
            kwargs = dict(kwargs)
            kwargs["item"] = f"VIP 自由計時｜{kwargs['item']}"
        return original_build_embed(*args, **kwargs)

    def timer_create_dispatch_plan(*args, **kwargs):
        nonlocal created_timer_order_id
        result = original_create_plan(*args, **kwargs)
        order_id = int(kwargs.get("order_id") or 0)
        if order_id <= 0 and args:
            try:
                order_id = int(args[0])
            except (TypeError, ValueError):
                order_id = 0
        if order_id <= 0:
            raise RuntimeError("VIP 自由計時無法取得 WebOrder ID。")

        note = _finalize_timer_web_order(
            order_id=order_id,
            customer_id=int(customer_id),
            initial_rule_key=initial_rule_key,
        )
        created_timer_order_id = order_id
        data["web_order_id"] = order_id
        data["web_order_note"] = note
        return result

    category_labels = dict(deps.category_labels)
    category_labels[source_category] = VIP_TIMER_CATEGORY_LABEL

    timed_deps = replace(
        deps,
        apply_financials=timer_apply_financials,
        add_financial_fields=timer_add_financial_fields,
        build_order_embed=timer_build_order_embed,
        create_dispatch_plan=timer_create_dispatch_plan,
        category_labels=category_labels,
        quantity_unit=lambda *_args, **_kwargs: "計時單",
    )

    try:
        result = await _ORIGINAL_WAITING_ORDER_CREATOR(
            interaction,
            customer_id=int(customer_id),
            channel_id=int(channel_id),
            deps=timed_deps,
        )
    except Exception:
        if created_timer_order_id is not None:
            _delete_timer_session(created_timer_order_id)
        raise

    # The generic dispatch runtime intentionally stores the canonical source-rule
    # category. Restore the draft-facing timer category so a later panel refresh
    # still opens on VIP 自由計時 instead of jumping back into a game category.
    data["category"] = VIP_TIMER_CATEGORY
    data["category_label"] = VIP_TIMER_CATEGORY_LABEL
    data["vip_timer_order"] = True
    data["vip_timer_source_category"] = source_category
    data["item_group"] = selected_game
    data["quantity"] = 1
    data["amount"] = 0
    data["total_amount"] = 0
    data["customer_pay_amount"] = 0
    data["payout_base_amount"] = 0
    deps.remember_order(int(channel_id), data)
    deps.save_data()
    return result


async def _timer_submit_from_view(view, interaction: discord.Interaction) -> None:
    from core.database import remember_order_data
    from core.permissions import is_customer_staff
    from services import self_service_ui_runtime as ui
    from services.self_service_runtime import _get_rule_from_self_service_data
    from services.order_runtime import normalize_self_service_staff_count

    if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
        await interaction.response.send_message("請聯繫客服送單。", ephemeral=True)
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
        return

    data = ui.SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.channel_id, {})
    if not is_vip_timer_self_service_data(data) or not data.get("item"):
        await interaction.response.send_message("請先選擇起始遊戲與玩法。", ephemeral=True)
        return

    try:
        assert_vip_timer_self_service_eligible(view.customer_id, check_open_order=True)
        rule = _get_rule_from_self_service_data(data)
        if not is_public_timer_rule(str(getattr(rule, "key", "") or "")):
            raise ValueError("這個玩法目前不能用於 VIP 自由計時，請重新選擇起始玩法。")
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    prepare_vip_timer_draft(data)
    normalize_self_service_staff_count(data)
    if bool(getattr(rule, "player_count_enabled", False)) and not data.get("player_count"):
        await interaction.response.send_modal(ui.SelfServicePlayerCountModal(view.customer_id, view.channel_id))
        return

    remember_order_data(view.channel_id, data)
    panel_message_id = interaction.message.id if interaction.message is not None else None
    await interaction.response.send_modal(
        ui.SelfServiceSubmitNoteModal(
            customer_id=view.customer_id,
            channel_id=view.channel_id,
            panel_message_id=panel_message_id,
        )
    )


def _install_category_state_patch() -> None:
    global _ORIGINAL_CATEGORY_STATE_APPLIER
    from services import order_runtime
    from services import self_service_selection_state as selection

    if _ORIGINAL_CATEGORY_STATE_APPLIER is None:
        _ORIGINAL_CATEGORY_STATE_APPLIER = selection.apply_self_service_category_selection

    original = _ORIGINAL_CATEGORY_STATE_APPLIER

    def timer_category_state(data: dict, category: str) -> None:
        original(data, category)
        if str(category) == VIP_TIMER_CATEGORY:
            data["vip_timer_order"] = True
        else:
            data.pop("vip_timer_order", None)
            data.pop("vip_timer_source_category", None)

    selection.apply_self_service_category_selection = timer_category_state
    order_runtime.apply_self_service_category_selection = timer_category_state


def _install_category_callback_patch() -> None:
    global _ORIGINAL_CATEGORY_CALLBACK
    from services import order_runtime

    if _ORIGINAL_CATEGORY_CALLBACK is None:
        _ORIGINAL_CATEGORY_CALLBACK = order_runtime.SelfServiceOrderCategorySelect.callback
    original = _ORIGINAL_CATEGORY_CALLBACK

    async def timer_category_callback(select, interaction: discord.Interaction):
        selected = str((select.values or [""])[0])
        if selected == VIP_TIMER_CATEGORY:
            try:
                assert_vip_timer_self_service_eligible(select.customer_id, check_open_order=True)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            refresh_vip_timer_self_service_catalog()
        await original(select, interaction)

    order_runtime.SelfServiceOrderCategorySelect.callback = timer_category_callback


def _install_panel_patch() -> None:
    global _ORIGINAL_PANEL_BUILDER
    from services import order_runtime
    from services import self_service_runtime as runtime
    from services import self_service_ui_runtime as ui

    if _ORIGINAL_PANEL_BUILDER is None:
        _ORIGINAL_PANEL_BUILDER = ui.build_self_service_panel_embed
    original = _ORIGINAL_PANEL_BUILDER

    def timer_panel(customer_id: int, data: dict, guild: discord.Guild | None = None):
        if is_vip_timer_self_service_data(data):
            return build_vip_timer_self_service_panel_embed(customer_id, data, guild)
        return original(customer_id, data, guild)

    ui.build_self_service_panel_embed = timer_panel
    runtime.build_self_service_panel_embed = timer_panel

    state = getattr(order_runtime, "_RUNTIME_STATE", None)
    if state is not None:
        order_runtime._RUNTIME_STATE = replace(
            state,
            self_service_panel_embed_builder=timer_panel,
        )


def _install_view_patch() -> None:
    global _ORIGINAL_VIEW_INIT
    from services import self_service_ui_runtime as ui

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def timer_view_init(view, customer_id: int, channel_id: int, selected_category: str | None = None):
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = str(selected_category or data.get("category") or "")
        if category == VIP_TIMER_CATEGORY or is_vip_timer_self_service_data(data):
            refresh_vip_timer_self_service_catalog()

        original(view, customer_id, channel_id, selected_category)

        if category != VIP_TIMER_CATEGORY and not is_vip_timer_self_service_data(data):
            return

        disabled_buttons = {
            "self_service_order_specified_staff_button",
            "self_service_order_point_benefit_button",
            "self_service_order_staff_price_button",
            "self_service_order_staff_discount_coupon_button",
        }
        for child in view.children:
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id in disabled_buttons:
                child.disabled = True
            elif custom_id == "self_service_order_item_select" and isinstance(child, discord.ui.Select):
                child.placeholder = "選擇起始遊戲"
            elif custom_id == "self_service_order_detail_select" and isinstance(child, discord.ui.Select):
                child.placeholder = "選擇起始玩法"
            elif custom_id == "self_service_order_quantity_select" and isinstance(child, discord.ui.Select):
                child.placeholder = "依實際時間計費"
                child.disabled = True
            elif custom_id == "self_service_order_go_payment_button" and isinstance(child, discord.ui.Button):
                child.label = "送出 VIP 計時單"

                async def timer_submit_callback(interaction: discord.Interaction, _view=view):
                    await _timer_submit_from_view(_view, interaction)

                child.callback = timer_submit_callback

    ui.SelfServiceOrderView.__init__ = timer_view_init


def _install_dispatch_patch() -> None:
    global _ORIGINAL_WAITING_ORDER_CREATOR
    from services import self_service_dispatch_runtime as dispatch
    from services import self_service_runtime as runtime

    if _ORIGINAL_WAITING_ORDER_CREATOR is None:
        _ORIGINAL_WAITING_ORDER_CREATOR = dispatch.create_waiting_acceptance_order
    original = _ORIGINAL_WAITING_ORDER_CREATOR

    async def timer_aware_creator(
        interaction: discord.Interaction,
        *,
        customer_id: int,
        channel_id: int,
        deps,
    ):
        data = deps.order_selections.setdefault(channel_id, {})
        if not is_vip_timer_self_service_data(data):
            return await original(
                interaction,
                customer_id=customer_id,
                channel_id=channel_id,
                deps=deps,
            )
        return await _create_vip_timer_waiting_order(
            interaction,
            customer_id=customer_id,
            channel_id=channel_id,
            deps=deps,
        )

    dispatch.create_waiting_acceptance_order = timer_aware_creator
    runtime.create_self_service_waiting_acceptance_order = timer_aware_creator


def install_vip_timer_self_service() -> None:
    """Expose the already-built VIP timer through Discord's self-service order UI."""
    global _INSTALLED
    if _INSTALLED:
        return

    refresh_vip_timer_self_service_catalog()
    _install_category_state_patch()
    _install_category_callback_patch()
    _install_panel_patch()
    _install_view_patch()
    _install_dispatch_patch()
    _INSTALLED = True


__all__ = [
    "VIP_TIMER_CATEGORY",
    "assert_vip_timer_self_service_eligible",
    "build_vip_timer_self_service_catalog",
    "install_vip_timer_self_service",
    "is_vip_timer_self_service_data",
    "prepare_vip_timer_draft",
    "refresh_vip_timer_self_service_catalog",
    "zero_vip_timer_financials",
]
