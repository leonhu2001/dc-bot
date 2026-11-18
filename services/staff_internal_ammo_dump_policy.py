from __future__ import annotations

from services.aw_collision_financials import calculate_aw_collision_financials


AMMO_DUMP_RULE_KEY = "staff_internal_ammo_dump_500m"
# Each unnamed tier pays the same worker base as its named tier.
# CS receives 25% of the unnamed difference; 500M historic figures remain unchanged.
AMMO_DUMP_PRICES_BY_RULE = {
    "staff_internal_ammo_dump_100m": (550, 620, 550),
    "staff_internal_ammo_dump_200m": (1080, 1220, 1080),
    "staff_internal_ammo_dump_300m": (1620, 1830, 1620),
    "staff_internal_ammo_dump_500m": (2650, 3000, 2650),
}
NAMED_PRICE = 2650
UNNAMED_PRICE = 3000
WORKER_PAYOUT = 2650
UNNAMED_STORE_MARGIN = UNNAMED_PRICE - WORKER_PAYOUT
UNNAMED_CS_MARGIN_RATE = 0.25
# Wages/payouts are recorded in integer T. 350T * 25% = 87.5T,
# rounded to 88T, leaving 262T with the shop.
UNNAMED_CS_PAYOUT = int(UNNAMED_STORE_MARGIN * UNNAMED_CS_MARGIN_RATE + 0.5)
UNNAMED_STORE_RETAINED = UNNAMED_STORE_MARGIN - UNNAMED_CS_PAYOUT
NAMED_SELECTION_KEY = "staff_internal_ammo_named"


def is_internal_ammo_dump_rule(rule_or_key) -> bool:
    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()
    return key in AMMO_DUMP_PRICES_BY_RULE


def selected_ammo_dump_named(data: dict | None) -> bool | None:
    if not isinstance(data, dict):
        return None
    value = data.get(NAMED_SELECTION_KEY)
    # Do not silently interpret an omitted flag or strings as 'no name'.
    return value if type(value) is bool else None


def require_ammo_dump_named_selection(rule_or_key, data: dict) -> None:
    if is_internal_ammo_dump_rule(rule_or_key) and selected_ammo_dump_named(data) is None:
        raise ValueError("內部倒子彈請先由客服選擇「有掛名」或「無掛名」才能送出。")


def calculate_internal_ammo_dump_cs_payout(
    rule_or_key, customer_pay_amount: int | None, worker_payout_base_amount: int | None,
) -> int:
    """CS gets 25% of a recognized unnamed price difference, never worker base.

    Check exact SKU/price/worker basis so historical overrides, discounts,
    urgent charges, and unrelated orders cannot fabricate a CS payout.
    """
    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()
    prices = AMMO_DUMP_PRICES_BY_RULE.get(key)
    if prices is None:
        return 0
    named_price, unnamed_price, worker_base = prices
    if (
        int(customer_pay_amount or 0) != unnamed_price
        or int(worker_payout_base_amount or 0) != worker_base
        or unnamed_price <= named_price
    ):
        return 0
    difference = unnamed_price - worker_base
    return int(difference * UNNAMED_CS_MARGIN_RATE + 0.5)


def calculate_internal_ammo_dump_financials(
    price_result, data: dict, rule_or_key=AMMO_DUMP_RULE_KEY,
) -> dict:
    rule_key = str(getattr(rule_or_key, "key", rule_or_key) or "")
    if rule_key not in AMMO_DUMP_PRICES_BY_RULE:
        raise ValueError("不是內部倒子彈商品。")
    named_price, unnamed_price, worker_payout = AMMO_DUMP_PRICES_BY_RULE[rule_key]
    named = selected_ammo_dump_named(data)
    customer_price = unnamed_price if named is False else named_price
    store_margin = customer_price - worker_payout if named is not None else 0
    customer_service_payout = (
        calculate_internal_ammo_dump_cs_payout(
            rule_key, customer_price, worker_payout
        )
        if named is not None else 0
    )

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
        payout_base_amount=worker_payout,
        store_margin_amount=store_margin,
        customer_service_payout_amount=customer_service_payout,
        store_retained_amount=store_margin - customer_service_payout,
        staff_internal_ammo_named=named,
    )
    return result


__all__ = [
    "AMMO_DUMP_RULE_KEY",
    "AMMO_DUMP_PRICES_BY_RULE",
    "NAMED_PRICE",
    "UNNAMED_PRICE",
    "WORKER_PAYOUT",
    "UNNAMED_STORE_MARGIN",
    "UNNAMED_CS_MARGIN_RATE",
    "UNNAMED_CS_PAYOUT",
    "UNNAMED_STORE_RETAINED",
    "NAMED_SELECTION_KEY",
    "is_internal_ammo_dump_rule",
    "selected_ammo_dump_named",
    "require_ammo_dump_named_selection",
    "calculate_internal_ammo_dump_financials",
    "calculate_internal_ammo_dump_cs_payout",
]
