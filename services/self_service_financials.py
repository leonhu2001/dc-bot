from __future__ import annotations

import json
from typing import Any, Callable

from services.aw_collision_financials import calculate_aw_collision_financials, is_aw_collision_rule

import discord

from services.point_benefit_catalog import (
    calculate_one_seat_service_bonus_value,
    resolve_rule_staff_count,
)
from services.self_service_point_benefits import (
    _adapt_order_point_benefit_for_rule,
    configure_self_service_point_benefits,
    get_customer_point_balance_for_order,
    get_order_point_item,
    get_selected_order_point_benefit,
    is_order_point_benefit_allowed_for_rule,
)
from services.vip_monthly_order_discount import (
    build_vip_monthly_discount_note,
    build_vip_monthly_discount_result,
    resolve_vip_monthly_cash_discount,
)


_get_rule_from_self_service_data: Callable[..., Any]
_is_specify_preference: Callable[..., bool]
_role_key_for_member: Callable[..., Any]
_to_int: Callable[..., int]
allocate_store_absorbed_fixed_discount: Callable[..., Any]
get_customer_reward_data: Callable[..., Any]
get_effective_member_level: Callable[..., Any]
get_self_service_quantity_unit: Callable[..., Any]
get_vip_discount_pay_rate: Callable[..., Any]


def is_self_service_staff_price_required(rule) -> bool:
    rule_key = str(getattr(rule, "key", "") or "").strip().lower()
    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
    return rule_key in {"farm_department_task", "custom_custom_order"} or pricing_type in {
        "manual",
        "staff",
        "custom",
    }


def get_self_service_staff_price(data: dict) -> int | None:
    raw_amount = data.get("manual_staff_amount")
    if raw_amount is None or str(raw_amount).strip() == "":
        return None
    try:
        amount = int(float(str(raw_amount).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None
    return max(0, amount)


def configure_self_service_financials(
    *,
    order_point_benefit_specs: dict,
    point_redeem_items_by_key: dict,
    get_rule_from_data: Callable[..., Any],
    is_specify_preference: Callable[..., bool],
    role_key_for_member: Callable[..., Any],
    to_int: Callable[..., int],
    store_absorbed_discount_allocator: Callable[..., Any],
    current_reward_points: Callable[..., int],
    customer_reward_data: Callable[..., Any],
    effective_member_level: Callable[..., Any],
    self_service_quantity_unit: Callable[..., Any],
    vip_discount_pay_rate: Callable[..., Any],
) -> None:
    global _get_rule_from_self_service_data
    global _is_specify_preference
    global _role_key_for_member
    global _to_int
    global allocate_store_absorbed_fixed_discount
    global get_customer_reward_data
    global get_effective_member_level
    global get_self_service_quantity_unit
    global get_vip_discount_pay_rate

    _get_rule_from_self_service_data = get_rule_from_data
    _is_specify_preference = is_specify_preference
    _role_key_for_member = role_key_for_member
    _to_int = to_int
    allocate_store_absorbed_fixed_discount = store_absorbed_discount_allocator
    get_customer_reward_data = customer_reward_data
    get_effective_member_level = effective_member_level
    get_self_service_quantity_unit = self_service_quantity_unit
    get_vip_discount_pay_rate = vip_discount_pay_rate
    configure_self_service_point_benefits(
        order_point_benefit_specs=order_point_benefit_specs,
        point_redeem_items_by_key=point_redeem_items_by_key,
        to_int=to_int,
        current_reward_points=current_reward_points,
        customer_reward_data=customer_reward_data,
    )


def _format_plain_amount(amount: int | None) -> str:
    if amount is None:
        return "客服待填價"
    return f"{int(amount or 0):,}"


def _price_int(src: dict, *keys, default=0):
    for key in keys:
        value = src.get(key)
        if value is None or str(value).strip() == "":
            continue
        value = _to_int(value, None)
        if value is not None:
            return int(value)
    return int(default)


def _price_rate(src: dict) -> float:
    try:
        value = float(
            src.get("discount_rate_percent", src.get("manual_discount_percent", 100))
        )
    except (TypeError, ValueError):
        value = 100.0
    value = max(0.0, min(100.0, value))
    mode = str(src.get("manual_discount_mode") or "").strip().lower()
    if mode == "pay_rate" or _price_int(src, "price_formula_version", default=0) >= 2:
        return value
    return 100.0 - value


def _price_snapshot(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def add_self_service_financial_breakdown_fields(
    embed: discord.Embed,
    src: dict,
    final_label="顧客應付",
):
    src = dict(src or {})
    original = max(
        0,
        _price_int(src, "service_original_amount", "original_amount", default=0),
    )
    percent_off = max(
        0,
        _price_int(src, "percent_discount_amount", "manual_discount_amount", default=0),
    )
    fixed = max(
        0,
        _price_int(src, "fixed_discount_amount", "cash_coupon_amount", default=0),
    )
    point_cash = max(0, _price_int(src, "point_discount_coupon_amount", default=0))
    specify_before = max(0, _price_int(src, "specified_fee_before_waiver", default=0))
    point_specify = max(0, _price_int(src, "point_waived_specify_fee", default=0))
    specify_effective = src.get("effective_specify_fee")
    if specify_effective is None:
        specify_effective = max(0, specify_before - point_specify)
    else:
        specify_effective = max(0, _to_int(specify_effective, 0) or 0)
    final = max(
        0,
        _price_int(src, "customer_pay_amount", "amount", "total_amount", default=0),
    )
    payout = max(0, _price_int(src, "payout_base_amount", default=0))
    rate = _price_rate(src)

    embed.add_field(name="商品原價", value=_format_plain_amount(original), inline=True)
    if rate < 100 or percent_off:
        embed.add_field(
            name="百分比折扣",
            value=f"折後 {_format_percent_value(rate)}%\n-{_format_plain_amount(percent_off)}",
            inline=True,
        )
    if fixed:
        reason = str(src.get("cash_coupon_reason") or "").strip()
        text = f"-{_format_plain_amount(fixed)}"
        if reason:
            text += f"\n{reason}"
        text += "\n店內吸收，不影響打手分潤"
        embed.add_field(name="固定折扣", value=text, inline=True)
    if point_cash:
        embed.add_field(
            name="點數折價",
            value=f"-{_format_plain_amount(point_cash)}\n店內吸收，不扣打手分潤",
            inline=True,
        )
    if specify_before:
        if specify_effective == 0:
            text = f"原 {_format_plain_amount(specify_before)}\n已免除"
        else:
            text = f"+{_format_plain_amount(specify_effective)}"
        embed.add_field(name="指定費", value=text, inline=True)

    embed.add_field(name=final_label, value=_format_plain_amount(final), inline=True)
    embed.add_field(name="打手分潤基準", value=_format_plain_amount(payout), inline=True)

    benefit_name = str(src.get("point_benefit_name") or "").strip()
    bonus = str(src.get("service_bonus_text") or "").strip()
    if benefit_name:
        lines = [f"{_price_int(src, 'point_benefit_cost', default=0)} 點｜{benefit_name}"]
        if point_cash:
            lines.append(f"已直接折抵價格：-{_format_plain_amount(point_cash)}")
        if bonus:
            lines.append(f"訂單備註：{bonus}")
        embed.add_field(name="點數福利", value="\n".join(lines), inline=False)
    elif bonus:
        embed.add_field(name="訂單福利備註", value=bonus, inline=False)

    service_promotion_text = str(src.get("service_promotion_text") or "").strip()
    if service_promotion_text:
        embed.add_field(name="活動加贈", value=service_promotion_text, inline=False)
    return embed


def _format_percent_value(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _parse_discount_percent_text(value: str | None) -> float:
    raw = str(value or "").strip().replace("%", "")
    if not raw:
        return 100.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("折後比例請輸入數字，例如 90 代表 9 折。") from exc
    if value < 0 or value > 100:
        raise ValueError("折後比例只能輸入 0～100。")
    return value


def _parse_cash_amount_text(value: str | None) -> int:
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0
    try:
        amount = int(float(raw))
    except ValueError as exc:
        raise ValueError("固定折扣金額請輸入數字，例如 100。") from exc
    if amount < 0:
        raise ValueError("固定折扣金額不能小於 0。")
    return amount


def _resolve_manual_discount_rate_percent(data: dict) -> float:
    raw = data.get("manual_discount_percent")
    if raw is None or str(raw).strip() == "":
        return 100.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(100.0, value))
    if str(data.get("manual_discount_mode") or "").strip().lower() == "pay_rate":
        return value
    return 100.0 - value


def _resolve_self_service_discount_rate(rule, data: dict) -> tuple[float, str, str, str]:
    """Resolve staff override first, otherwise apply the customer's effective VIP."""
    raw = data.get("manual_discount_percent")
    override = data.get("manual_discount_percent_override")
    if override is None:
        override = (
            data.get("manual_price_adjustment_set_by") is not None
            and raw is not None
            and str(raw).strip() != ""
            and _resolve_manual_discount_rate_percent(data) < 100
        )
    if bool(override):
        return (
            _resolve_manual_discount_rate_percent(data),
            str(data.get("manual_discount_reason") or "").strip(),
            "manual",
            "",
        )

    customer_id = _to_int(data.get("customer_id"))
    vip_name = "普通魔丸"
    if customer_id is not None:
        try:
            reward_data = get_customer_reward_data(int(customer_id))
            vip_name = str(get_effective_member_level(reward_data).get("name") or "普通魔丸")
        except Exception:
            vip_name = "普通魔丸"

    rate = float(
        get_vip_discount_pay_rate(
            vip_name,
            category=str(getattr(rule, "category", "") or ""),
            rule_key=str(getattr(rule, "key", "") or ""),
        )
    )
    reason = f"{vip_name} 自動 VIP 折扣" if rate < 100 else ""
    return rate, reason, ("vip" if rate < 100 else "none"), vip_name


def calculate_manual_price_adjustment(base_amount: int, data: dict) -> dict:
    original = max(0, int(base_amount or 0))
    rate = _resolve_manual_discount_rate_percent(data)
    after_percent = max(0, min(original, int(round(original * rate / 100))))
    percent_off = original - after_percent
    raw_fixed = data.get("fixed_discount_amount")
    if raw_fixed is None:
        raw_fixed = data.get("cash_coupon_amount")
    fixed = max(0, min(after_percent, _to_int(raw_fixed, 0) or 0))
    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
    )
    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "service_original_amount": original,
        "original_amount": original,
        "manual_discount_percent": rate,
        "discount_rate_percent": rate,
        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,
        "payout_base_amount": allocation.payout_base_amount,
        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,
        "store_absorbed_amount": allocation.store_absorbed_amount,
        "customer_pay_amount": allocation.customer_pay_amount,
        "manual_discount_reason": str(data.get("manual_discount_reason") or "").strip(),
        "cash_coupon_reason": str(data.get("cash_coupon_reason") or "").strip(),
    }


def apply_manual_price_adjustment_to_order_data(data: dict, base_amount: int) -> dict:
    adjustment = calculate_manual_price_adjustment(base_amount, data)
    data.update(adjustment)
    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = _format_plain_amount(adjustment["customer_pay_amount"])
    return adjustment


def _quote_preview_lines_for_self_service(
    data: dict,
    guild: discord.Guild | None = None,
) -> list[tuple[str, str]]:
    if not data.get("item"):
        return []
    try:
        rule = _get_rule_from_self_service_data(data)
        from services.order_rules import calculate_price, get_required_staff_count, rule_role_labels
    except Exception:
        return []

    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = str(data.get("companion_preference") or "不指定陪玩/打手").strip()
    player_count = _to_int(data.get("player_count"), 1) or 1
    specified_staff_ids = [str(item) for item in data.get("specified_staff_ids") or []]
    specified_roles: list[str] = []
    specified_mentions: list[str] = []
    if guild is not None and specified_staff_ids:
        for staff_id in specified_staff_ids:
            try:
                member = guild.get_member(int(staff_id))
            except Exception:
                member = None
            if member is not None:
                role_key = _role_key_for_member(rule, member)
                if role_key:
                    specified_roles.append(role_key)
                specified_mentions.append(member.mention)
            else:
                specified_mentions.append(f"<@{staff_id}>")

    try:
        price = calculate_price(
            rule,
            quantity=quantity,
            player_count=player_count,
            specified_roles=specified_roles,
        )
    except Exception:
        price = None
    required_staff_count = get_required_staff_count(rule, player_count)
    lines: list[tuple[str, str]] = []

    if price is None:
        lines.append(("預估金額", "客服待填價"))
    else:
        adjustment = calculate_self_service_financials(rule, price, data)
        if adjustment.get("manual_price_missing"):
            lines.append(("顧客應付", "客服待填價"))
        else:
            lines.append(("顧客應付", _format_plain_amount(adjustment["customer_pay_amount"])))

        detail_parts = [
            "客服待填價格"
            if adjustment.get("manual_price_missing")
            else f"商品原價 {_format_plain_amount(adjustment['service_original_amount'])}"
        ]
        if int(price.specify_fee or 0) > 0:
            detail_parts.append(f"指定費原本 {_format_plain_amount(price.specify_fee)}")
        if adjustment["point_waived_specify_fee"] > 0:
            detail_parts.append(
                f"點數免指定費 -{_format_plain_amount(adjustment['point_waived_specify_fee'])}"
            )
        if adjustment.get("point_free_first_hour_amount", 0) > 0:
            detail_parts.append(
                f"首小時免費 -{_format_plain_amount(adjustment['point_free_first_hour_amount'])}"
            )
        if getattr(price, "free_specify_fee", False):
            detail_parts.append("2 小時以上免指定費")
        if adjustment["manual_discount_amount"] > 0:
            reason = adjustment["manual_discount_reason"] or "未填原因"
            detail_parts.append(
                f"百分比折扣｜折後 {_format_percent_value(adjustment['manual_discount_percent'])}%"
                f" -{_format_plain_amount(adjustment['manual_discount_amount'])}（{reason}）"
            )
        detail_parts.append(f"打手分潤基準 {_format_plain_amount(adjustment['payout_base_amount'])}")
        if adjustment["point_discount_coupon_amount"] > 0:
            detail_parts.append(
                f"點數折價 -{_format_plain_amount(adjustment['point_discount_coupon_amount'])}（店內吸收）"
            )
        if adjustment["cash_coupon_amount"] > 0:
            reason = adjustment["cash_coupon_reason"] or "未填原因"
            detail_parts.append(
                f"固定折扣 -{_format_plain_amount(adjustment['cash_coupon_amount'])}"
                f"（{reason}，店內吸收，不影響打手分潤）"
            )
        if adjustment.get("benefit_discount_amount", 0) > 0:
            detail_parts.append(
                f"累積福利 -{_format_plain_amount(adjustment['benefit_discount_amount'])}"
                "（店內吸收，不影響打手分潤）"
            )
        lines.append(("金額明細", "｜".join(detail_parts)))

        if adjustment["point_benefit_name"]:
            point_text = f"{adjustment['point_benefit_cost']} 點｜{adjustment['point_benefit_name']}"
            if adjustment["service_bonus_text"]:
                point_text += f"｜{adjustment['service_bonus_text']}"
            lines.append(("點數福利", point_text))
        if adjustment.get("benefit_coupon_title"):
            lines.append(("我的福利", str(adjustment["benefit_coupon_title"])))
        promotion_text = str(adjustment.get("service_promotion_text") or "").strip()
        if promotion_text:
            lines.append(("活動加贈", promotion_text))

    unit = get_self_service_quantity_unit(rule.label, data)
    lines.append(("數量", f"{quantity} {unit}"))
    if getattr(rule, "player_count_enabled", False):
        lines.append(("陪玩人數", f"{player_count} 位"))
    lines.append(("接單需求", f"{required_staff_count} 位"))
    lines.append(("可接職位", rule_role_labels(rule)))

    if bool(getattr(rule, "allow_specify", False)):
        max_spec = rule.max_specified_count or required_staff_count
        if _is_specify_preference(companion_preference):
            if specified_mentions:
                lines.append(("指定狀態", "已選擇指定"))
                lines.append(("指定人員", "、".join(specified_mentions)))
            else:
                lines.append(
                    (
                        "指定狀態",
                        f"已選擇指定，尚未選擇成員\n可指定人數：最多 {max_spec} 位",
                    )
                )
        else:
            lines.append(("指定狀態", "目前不指定"))
            lines.append(("可指定人數", f"此項目可指定，最多 {max_spec} 位"))
    else:
        lines.append(("指定狀態", "不可指定"))

    if not rule.point_benefits_allowed:
        lines.append(("點數福利", "此分類不可使用點數福利"))
    if rule.min_quantity and int(rule.min_quantity) > 1:
        lines.append(("最低數量", f"{rule.min_quantity} {unit}"))
    return lines


def add_self_service_quote_preview(
    embed: discord.Embed,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    lines = _quote_preview_lines_for_self_service(data, guild)
    if not lines:
        return embed
    preview_text = "\n".join(f"**{name}：** {value}" for name, value in lines)
    embed.add_field(name="訂單試算", value=preview_text[:1024], inline=False)
    return embed


def _format_point_hours(hours) -> str:
    try:
        value = float(hours or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "0H"
    if value == 0.5:
        return "30 分鐘"
    if value.is_integer():
        return f"{int(value)}H"
    return f"{value:g}H"


def calculate_self_service_financials(rule, price_result, data: dict) -> dict:
    if is_aw_collision_rule(rule):
        return calculate_aw_collision_financials(price_result, data)

    manual_price = get_self_service_staff_price(data)
    specify_before = max(0, int(getattr(price_result, "specify_fee", 0) or 0))
    staff_adjust = int(getattr(price_result, "staff_adjustment_amount", 0) or 0)
    if is_self_service_staff_price_required(rule):
        service_original = max(0, int(manual_price or 0))
    else:
        service_original = max(
            0,
            int(getattr(price_result, "base_amount", 0) or 0) + staff_adjust,
        )

    benefit = get_selected_order_point_benefit(data, rule)
    bkey = str(benefit.get("key")) if benefit else None
    bname = str(benefit.get("name")) if benefit else ""
    bcost = int(benefit.get("cost") or 0) if benefit else 0
    bkind = str(benefit.get("kind") or "") if benefit else ""
    point_specify = 0
    point_cash = 0
    legacy_free_hour = 0
    extra_hours = 0.0
    extra_games = 0

    if bkind == "free_specify_fee":
        point_specify = specify_before
    elif bkind == "cash_discount":
        point_cash = max(0, int(benefit.get("amount") or 0))
    elif bkind == "extra_hours":
        extra_hours = max(0.0, float(benefit.get("hours") or 0))
    elif bkind in {"extra_games", "extra_game"}:
        extra_games = max(0, int(benefit.get("games") or 0))
    elif bkind == "free_first_hour":
        try:
            from services.order_rules import calculate_price

            pc = _to_int(data.get("player_count"), 1) or 1
            first = calculate_price(rule, quantity=1, player_count=pc, specified_roles=[])
            legacy_free_hour = max(0, int(getattr(first, "base_amount", 0) or 0))
        except Exception:
            qty = max(1, _to_int(data.get("quantity"), 1) or 1)
            legacy_free_hour = max(
                0,
                int(getattr(price_result, "base_amount", 0) or 0) // qty,
            )

    point_specify = min(point_specify, specify_before)
    specify_effective = max(0, specify_before - point_specify)
    legacy_free_hour = min(legacy_free_hour, service_original)
    discountable = max(0, service_original - legacy_free_hour)
    rate, discount_reason, discount_source, vip_level_name = _resolve_self_service_discount_rate(
        rule, data
    )
    after_percent = max(0, min(discountable, int(round(discountable * rate / 100))))
    percent_off = max(0, discountable - after_percent)

    raw_fixed = data.get("fixed_discount_amount")
    if raw_fixed is None:
        raw_fixed = data.get("cash_coupon_amount")
    fixed = max(0, min(after_percent, _to_int(raw_fixed, 0) or 0))
    after_fixed = max(0, after_percent - fixed)
    point_cash = max(0, min(point_cash, after_fixed))
    selected_vip_monthly, vip_monthly_cash = resolve_vip_monthly_cash_discount(
        data,
        has_point_benefit=benefit is not None,
        max_discount_amount=after_fixed,
    )
    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=point_cash + vip_monthly_cash,
        extra_customer_charge_amount=specify_effective,
    )

    from services.self_service_loyalty_discount import resolve_self_service_loyalty_discount

    loyalty_discount = resolve_self_service_loyalty_discount(
        data=data,
        rule=rule,
        point_benefit_selected=benefit is not None,
        vip_monthly_selected=selected_vip_monthly is not None,
        available_service_amount=after_fixed,
        to_int=_to_int,
    )
    benefit_service_value = loyalty_discount["service_value"]
    benefit_discount_amount = loyalty_discount["discount_amount"]
    one_seat_point_service_value = calculate_one_seat_service_bonus_value(
        rule=rule,
        service_original=service_original,
        quantity=data.get("quantity"),
        player_count=data.get("player_count"),
        extra_hours=extra_hours,
        extra_games=extra_games,
    )
    funded_point_service_seats = 1
    if benefit and one_seat_point_service_value > 0:
        try:
            requested_funded_seats = int(benefit.get("seat_count") or 0)
        except (TypeError, ValueError):
            requested_funded_seats = 0
        if requested_funded_seats > 0:
            actual_seats = resolve_rule_staff_count(rule, data.get("player_count", 1))
            funded_point_service_seats = min(
                max(1, requested_funded_seats),
                max(1, int(actual_seats or 1)),
            )
    point_service_value = one_seat_point_service_value * funded_point_service_seats

    # Waived specify fees were never collected, so they are not payout/store value.
    # Current seat-aware service rewards, however, fund every selected seat directly.
    payout_base = allocation.payout_base_amount + point_service_value
    customer_pay = max(0, allocation.customer_pay_amount - benefit_discount_amount)
    notes: list[str] = []
    if legacy_free_hour:
        notes.append(f"舊版福利：首小時免費 -{_format_plain_amount(legacy_free_hour)}")
    if extra_hours:
        seat_note = (
            f"{funded_point_service_seats} 位陪玩同步加贈"
            if funded_point_service_seats > 1
            else "1 位陪玩"
        )
        notes.append(f"服務時間 +{_format_point_hours(extra_hours)}（{seat_note}）")
    if extra_games:
        if bkind == "extra_games":
            seat_note = (
                f"{funded_point_service_seats} 位陪玩同步加贈"
                if funded_point_service_seats > 1
                else "1 位陪玩"
            )
            notes.append(f"服務局數 +{extra_games} 局（{seat_note}）")
        else:
            notes.append(f"加場 {extra_games} 場保撤")
    if point_specify:
        notes.append(f"免指定費 -{_format_plain_amount(point_specify)}")
    vip_monthly_note = build_vip_monthly_discount_note(
        selected_vip_monthly,
        vip_monthly_cash,
        formatter=_format_plain_amount,
    )
    if vip_monthly_note:
        notes.append(vip_monthly_note)

    purchased_service_quantity = max(1, _to_int(data.get("quantity"), 1) or 1)
    actual_service_quantity = max(
        purchased_service_quantity,
        int(getattr(price_result, "service_quantity", purchased_service_quantity) or purchased_service_quantity),
    )
    automatic_service_bonus_quantity = max(
        0,
        actual_service_quantity - purchased_service_quantity,
    )
    service_unit_text = str(getattr(rule, "unit_label", "單") or "單").strip()
    service_promotion_text = ""
    if automatic_service_bonus_quantity > 0:
        service_promotion_text = (
            f"活動加贈：購買 {purchased_service_quantity}{service_unit_text}，"
            f"額外贈送 {automatic_service_bonus_quantity}{service_unit_text}"
            f"｜活動後共 {actual_service_quantity}{service_unit_text}"
        )

    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "manual_price_missing": bool(
            is_self_service_staff_price_required(rule) and manual_price is None
        ),
        "manual_staff_amount": manual_price,
        "manual_staff_price_reason": str(data.get("manual_staff_price_reason") or "").strip(),
        "rule_original_amount": service_original + specify_before,
        "service_original_amount": service_original,
        "original_amount": service_original,
        "priced_amount": discountable,
        "manual_discount_percent": rate,
        "discount_rate_percent": rate,
        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,
        "manual_discount_reason": discount_reason,
        "discount_source": discount_source,
        "vip_level_name": vip_level_name,
        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,
        "cash_coupon_reason": str(data.get("cash_coupon_reason") or "").strip(),
        "point_discount_coupon_amount": point_cash,
        **build_vip_monthly_discount_result(selected_vip_monthly, vip_monthly_cash),
        "specified_fee_before_waiver": specify_before,
        "effective_specify_fee": specify_effective,
        "point_waived_specify_fee": point_specify,
        "point_free_first_hour_amount": legacy_free_hour,
        "point_extra_hours": extra_hours,
        "point_extra_games": extra_games,
        "point_benefit_key": bkey,
        "point_benefit_name": bname,
        "point_benefit_cost": bcost,
        "point_benefit_summary": str(benefit.get("summary") or "") if benefit else "",
        "service_bonus_text": "｜".join(notes),
        "service_quantity": actual_service_quantity,
        "service_bonus_quantity": automatic_service_bonus_quantity,
        "service_promotion_text": service_promotion_text,
        "payout_base_amount": payout_base,
        "benefit_coupon_id": loyalty_discount["coupon_id"],
        "benefit_coupon_title": loyalty_discount["coupon_title"],
        "benefit_coupon": loyalty_discount["coupon"],
        "benefit_service_note": loyalty_discount["service_note"],
        "benefit_service_value": benefit_service_value,
        "benefit_discount_amount": benefit_discount_amount,
        "point_service_value": point_service_value,
        "store_absorbed_amount": (
            allocation.store_absorbed_amount
            + benefit_discount_amount
            + point_service_value
        ),
        "customer_pay_amount": customer_pay,
    }


def apply_self_service_financials_to_order_data(data: dict, rule, price_result) -> dict:
    adjustment = calculate_self_service_financials(rule, price_result, data)
    data.update(adjustment)
    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = _format_plain_amount(adjustment["customer_pay_amount"])
    return adjustment
