from __future__ import annotations

from services.aw_collision_financials import calculate_aw_collision_financials


AMMO_DUMP_RULE_KEY = "staff_internal_ammo_dump_500m"
NAMED_PRICE = 2650
UNNAMED_PRICE = 3000
WORKER_PAYOUT = 2650
UNNAMED_STORE_MARGIN = UNNAMED_PRICE - WORKER_PAYOUT
NAMED_SELECTION_KEY = "staff_internal_ammo_named"


def is_internal_ammo_dump_rule(rule_or_key) -> bool:
    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()
    return key == AMMO_DUMP_RULE_KEY


def selected_ammo_dump_named(data: dict | None) -> bool | None:
    if not isinstance(data, dict):
        return None
    value = data.get(NAMED_SELECTION_KEY)
    # Do not silently interpret an omitted flag or strings as 'no name'.
    return value if type(value) is bool else None


def require_ammo_dump_named_selection(rule_or_key, data: dict) -> None:
    if is_internal_ammo_dump_rule(rule_or_key) and selected_ammo_dump_named(data) is None:
        raise ValueError("倒子彈 500M 請先由客服選擇「有掛名」或「無掛名」才能送出。")


def calculate_internal_ammo_dump_financials(price_result, data: dict) -> dict:
    named = selected_ammo_dump_named(data)
    customer_price = UNNAMED_PRICE if named is False else NAMED_PRICE
    store_margin = customer_price - WORKER_PAYOUT if named is not None else 0

    # Match direct-settlement farm/AW fields, deliberately excluding discounts
    # and manual price overrides. The named flag alone controls this product.
    result = calculate_aw_collision_financials(price_result, {})
    result.update(
        manual_price_missing=named is None,
        manual_staff_amount=None,
        manual_staff_price_reason="",
        rule_original_amount=customer_price,
        service_original_amount=customer_price,
        original_amount=customer_price,
        priced_amount=customer_price,
        customer_pay_amount=customer_price,
        payout_base_amount=WORKER_PAYOUT,
        store_margin_amount=store_margin,
        staff_internal_ammo_named=named,
    )
    return result


__all__ = [
    "AMMO_DUMP_RULE_KEY",
    "NAMED_PRICE",
    "UNNAMED_PRICE",
    "WORKER_PAYOUT",
    "UNNAMED_STORE_MARGIN",
    "NAMED_SELECTION_KEY",
    "is_internal_ammo_dump_rule",
    "selected_ammo_dump_named",
    "require_ammo_dump_named_selection",
    "calculate_internal_ammo_dump_financials",
]
