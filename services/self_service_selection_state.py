from __future__ import annotations

from typing import Any

from services.orders import get_order_item_details_for_group


# Benefit selections and calculated quote fields belong to one concrete product.
# They must never leak into another category / item / detail selection.
_PRODUCT_DEPENDENT_KEYS = (
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
    "service_bonus_text",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_discount_amount",
    "benefit_service_note",
    "store_absorbed_amount",
    "customer_pay_amount",
    "payout_base_amount",
    "amount",
    "total_amount",
    "amount_text",
    "rule_original_amount",
    "service_original_amount",
    "original_amount",
    "priced_amount",
    "manual_discount_amount",
    "percent_discount_amount",
    "discount_rate_percent",
    "discount_source",
    "vip_level_name",
    "effective_specify_fee",
    "specified_fee_before_waiver",
    "price_formula_version",
    # Timer identity belongs to the selected timer product, never to a later
    # ordinary product selected in the same ticket draft.
    "vip_timer_order",
    "vip_timer_source_category",
    # A manually entered base price belongs to one product only. Percentage/fixed
    # discounts are order-level inputs and are recalculated against the new product.
    "manual_staff_amount",
    "manual_staff_price_reason",
    "manual_staff_price_set_by",
    "manual_staff_price_set_at",
)


def clear_product_dependent_selection_state(data: dict[str, Any]) -> None:
    for key in _PRODUCT_DEPENDENT_KEYS:
        data.pop(key, None)
    data.pop("payment_method", None)


def _reset_player_count_for_selected_rule(data: dict[str, Any]) -> None:
    rule_key = str(data.get("order_rule_key") or "").strip()
    if not rule_key:
        data.pop("player_count", None)
        return
    try:
        from services.order_rules import ORDER_RULES
        from services.multi_seat_order_policy_20261028 import get_rule_player_count_bounds

        rule = ORDER_RULES.get(rule_key)
        if rule is None:
            data.pop("player_count", None)
            return
        _minimum, _maximum, default, _selectable = get_rule_player_count_bounds(rule)
        data["player_count"] = int(default)
    except Exception:
        data.pop("player_count", None)


def apply_self_service_category_selection(data: dict[str, Any], category: str) -> None:
    data["category"] = category
    for key in (
        "item_group",
        "item_detail_value",
        "item",
        "order_rule_key",
        "quantity",
        "player_count",
        "specified_staff_ids",
        "companion_preference",
    ):
        data.pop(key, None)
    clear_product_dependent_selection_state(data)


def apply_self_service_detail_selection(data: dict[str, Any], detail: dict[str, Any]) -> None:
    clear_product_dependent_selection_state(data)
    data["item_detail_value"] = str(detail.get("value") or "")
    data["item"] = str(detail.get("item") or detail.get("label") or "")
    data["order_rule_key"] = str(detail.get("rule_key") or "")

    # Legacy detail rows may still carry player_count. New storefront rows do not;
    # the shared count control is the only customer-facing source of truth.
    if detail.get("player_count") is not None:
        data["player_count"] = int(detail["player_count"])
    else:
        _reset_player_count_for_selected_rule(data)

    data["quantity"] = int(detail.get("min_quantity") or 1)
    data.pop("specified_staff_ids", None)
    data["companion_preference"] = "不指定陪玩/打手"


def apply_self_service_item_group_selection(
    data: dict[str, Any],
    selected_group: str,
) -> dict[str, Any] | None:
    data["item_group"] = selected_group
    for key in ("item_detail_value", "item", "order_rule_key", "player_count", "specified_staff_ids"):
        data.pop(key, None)
    clear_product_dependent_selection_state(data)
    data["companion_preference"] = "不指定陪玩/打手"

    details = get_order_item_details_for_group(data.get("category"), selected_group)
    if len(details) == 1:
        detail = details[0]
        apply_self_service_detail_selection(data, detail)
        return detail

    data["quantity"] = 1
    return None
