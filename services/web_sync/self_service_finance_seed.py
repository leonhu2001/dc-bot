from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_SETTLED_FINANCE_KEYS = (
    "price_formula_version",
    "manual_discount_mode",
    "service_original_amount",
    "manual_staff_amount",
    "manual_staff_price_reason",
    "manual_discount_percent",
    "discount_rate_percent",
    "manual_discount_amount",
    "percent_discount_amount",
    "manual_discount_reason",
    "cash_coupon_amount",
    "fixed_discount_amount",
    "cash_coupon_reason",
    "specified_fee_before_waiver",
    "effective_specify_fee",
    "point_benefit_key",
    "point_benefit_name",
    "point_benefit_cost",
    "point_discount_coupon_amount",
    "point_waived_specify_fee",
    "point_free_first_hour_amount",
    "point_extra_hours",
    "point_extra_games",
    "vip_monthly_benefit_id",
    "vip_monthly_benefit_key",
    "vip_monthly_benefit_title",
    "vip_monthly_cash_amount",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_discount_amount",
    "benefit_service_note",
    "service_bonus_text",
    "service_quantity",
    "service_bonus_quantity",
    "service_promotion_text",
    "original_amount",
    "rule_original_amount",
    "payout_base_amount",
    "customer_pay_amount",
    "store_absorbed_amount",
)


def seed_settled_website_finance(
    data: dict[str, Any],
    *,
    price_snapshot: Mapping[str, Any],
    order: Mapping[str, Any],
) -> None:
    """Copy the authoritative website quote into Discord self-service state."""
    for key in _SETTLED_FINANCE_KEYS:
        value = price_snapshot.get(key)
        if value is None:
            value = order.get(key)
        if value is not None:
            data[key] = value

    point_key = str(price_snapshot.get("point_benefit_key") or "").strip()
    if point_key:
        data["selected_point_benefit_key"] = point_key
        data["point_benefit_key"] = point_key

    vip_monthly_id = price_snapshot.get("vip_monthly_benefit_id")
    if vip_monthly_id not in (None, ""):
        data["selected_vip_monthly_benefit_id"] = vip_monthly_id

    benefit_coupon_id = price_snapshot.get("benefit_coupon_id")
    if benefit_coupon_id not in (None, ""):
        data["selected_benefit_coupon_id"] = benefit_coupon_id

    data["website_finance_settled"] = True
