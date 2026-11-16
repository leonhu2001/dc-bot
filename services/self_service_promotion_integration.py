from __future__ import annotations

from services.order_discounts import FUNDING_SHARED


_INSTALLED = False


def _original_service_amount(rule, data: dict, fallback: int) -> int:
    """Resolve the current order's original eligible service amount.

    Manual-price rules must use the current staff-entered amount. Standard rules
    are recalculated from the current quantity/player count first so changing an
    order after selecting a benefit cannot keep an older, higher eligibility
    amount in the draft. Stored values are only a compatibility fallback.
    """
    try:
        from services.self_service_financials import (
            get_self_service_staff_price,
            is_self_service_staff_price_required,
        )

        if is_self_service_staff_price_required(rule):
            manual = get_self_service_staff_price(data)
            return max(0, int(manual or 0))
    except Exception:
        pass

    try:
        from services.order_rules import calculate_price

        price = calculate_price(
            rule,
            quantity=max(1, int(data.get("quantity") or 1)),
            player_count=max(1, int(data.get("player_count") or 1)),
            specified_roles=[],
        )
        return max(
            0,
            int(getattr(price, "base_amount", 0) or 0)
            + int(getattr(price, "staff_adjustment_amount", 0) or 0),
        )
    except Exception:
        pass

    values = [
        data.get("service_original_amount"),
        data.get("original_amount"),
        data.get("manual_staff_amount"),
        fallback,
    ]
    for value in values:
        try:
            amount = int(value or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount > 0:
            return amount
    return 0


def _category_for_rule_key(rule_key: str) -> str:
    try:
        from services.order_rules import get_rule

        return str(getattr(get_rule(str(rule_key or "")), "category", "") or "")
    except Exception:
        return ""


def resolve_promotion_loyalty_discount(
    *, data: dict, rule, point_benefit_selected: bool,
    vip_monthly_selected: bool, available_service_amount: int,
) -> dict:
    """Resolve an issued promotion in the canonical benefit calculation."""
    from services import promotion_benefits as promotion
    from services import self_service_financials as financials

    selected_id = data.get("selected_benefit_coupon_id")
    if point_benefit_selected or vip_monthly_selected:
        raise ValueError("優惠福利、VIP 每月福利券與點數福利同張訂單只能擇一使用。")
    customer_id = data.get("customer_id")
    if not customer_id:
        raise ValueError("找不到會員資料，無法使用這張優惠福利。")
    original = _original_service_amount(rule, data, available_service_amount)
    try:
        rate, _reason, source, _vip_level = (
            financials._resolve_self_service_discount_rate(rule, data)
        )
        vip_active = source == "vip" and float(rate) < 100
    except Exception:
        vip_active = False
    benefit = promotion.get_applicable_issued_benefit(
        selected_id,
        customer_discord_id=customer_id,
        rule_key=str(getattr(rule, "key", "") or ""),
        category=str(getattr(rule, "category", "") or ""),
        original_service_amount=original,
        vip_discount_active=vip_active,
        point_selected=False,
    )
    if benefit is None:
        raise ValueError("這張優惠福利已使用、已保留，或目前訂單未達使用條件。")

    specify_fee = max(
        0, int(data.get("effective_specify_fee")
               or data.get("specified_fee_before_waiver") or 0),
    )
    quantity = max(1, int(data.get("quantity") or 1))
    player_count = max(1, int(data.get("player_count") or 1))
    try:
        from services.order_rules import get_required_staff_count
        staff_count = max(1, int(get_required_staff_count(rule, player_count) or 1))
    except Exception:
        staff_count = player_count

    discount = promotion.calculate_discount_amount(
        benefit,
        service_amount_after_percent=max(0, int(available_service_amount or 0)),
        original_service_amount=original,
        specify_fee=specify_fee,
        quantity=quantity,
        staff_count=staff_count,
    )
    return {
        "coupon": benefit,
        "coupon_id": int(selected_id),
        "coupon_title": str(benefit.get("title") or "優惠福利"),
        "service_note": promotion.benefit_note(benefit),
        "service_value": 0,
        "discount_amount": int(discount),
    }


def apply_promotion_funding_snapshot(result: dict) -> dict:
    """Persist exact promotion funding without touching other discounts."""
    from services import promotion_benefits as promotion

    benefit = result.get("benefit_coupon")
    if not isinstance(benefit, dict) or benefit.get("source") != "promotion":
        return result
    result = dict(result)
    discount = max(0, int(result.get("benefit_discount_amount") or 0))
    result["promotion_benefit_id"] = int(benefit.get("issued_benefit_id") or 0)
    result["promotion_discount_amount"] = discount
    funding = str(benefit.get("funding") or promotion.FUNDING_STORE)
    result["promotion_funding"] = funding
    result["promotion_rules_snapshot"] = dict(benefit.get("rules") or {})
    result["benefit_service_value"] = 0
    if funding == FUNDING_SHARED and discount > 0:
        result["payout_base_amount"] = max(
            0, int(result.get("payout_base_amount") or 0) - discount,
        )
        result["store_absorbed_amount"] = max(
            0, int(result.get("store_absorbed_amount") or 0) - discount,
        )
    return result


def install_self_service_promotion_integration() -> None:
    """Compatibility hook; issued coupons are resolved at source."""
    global _INSTALLED
    _INSTALLED = True
