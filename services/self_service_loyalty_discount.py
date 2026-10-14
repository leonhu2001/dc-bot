from __future__ import annotations

from typing import Any, Callable


def resolve_self_service_loyalty_discount(
    *,
    data: dict,
    rule,
    point_benefit_selected: bool,
    vip_monthly_selected: bool,
    available_service_amount: int,
    to_int: Callable[..., int],
) -> dict[str, Any]:
    """Resolve a stored or same-order loyalty reward for Discord checkout.

    Loyalty is store-funded: this result only tells the caller how much to
    subtract from customer payment. Companion payout must remain unchanged.
    """
    from services.loyalty_benefits import (
        calculate_coupon_service_value,
        coupon_service_note,
        get_applicable_coupon,
        preview_same_order_benefit,
    )

    selected_coupon_id = data.get("selected_benefit_coupon_id")
    selected_same_order = bool(data.get("selected_same_order_benefit"))
    if selected_coupon_id in (None, "") and not selected_same_order:
        return {
            "coupon": None,
            "coupon_id": None,
            "coupon_title": "",
            "service_note": "",
            "service_value": 0,
            "discount_amount": 0,
        }

    if point_benefit_selected or vip_monthly_selected:
        raise ValueError("福利券、VIP 每月福利券與點數福利同張訂單只能擇一使用。")

    customer_id = data.get("customer_id")
    player_count = to_int(data.get("player_count"), 1) or 1
    rule_key = str(getattr(rule, "key", ""))
    selected_coupon = None

    if selected_coupon_id not in (None, ""):
        if customer_id:
            selected_coupon = get_applicable_coupon(
                selected_coupon_id,
                customer_id=customer_id,
                rule_key=rule_key,
                player_count=player_count,
            )
        if selected_coupon is None:
            raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")
    else:
        if customer_id:
            selected_coupon = preview_same_order_benefit(
                customer_id,
                rule_key=rule_key,
                quantity=max(1, to_int(data.get("quantity"), 1) or 1),
                player_count=player_count,
            )
        if selected_coupon is None:
            raise ValueError("本單目前尚未達到可立即折抵的累積門檻。")

    service_value = calculate_coupon_service_value(
        rule_key=rule_key,
        player_count=player_count,
        coupon=selected_coupon,
    )
    discount_amount = max(
        0,
        min(max(0, int(available_service_amount or 0)), int(service_value or 0)),
    )

    coupon_id = selected_coupon.get("id")
    return {
        "coupon": dict(selected_coupon),
        "coupon_id": int(coupon_id) if coupon_id not in (None, "") else None,
        "coupon_title": str(selected_coupon.get("title") or ""),
        "service_note": coupon_service_note(selected_coupon),
        "service_value": int(service_value or 0),
        "discount_amount": discount_amount,
    }
