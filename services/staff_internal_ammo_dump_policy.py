from __future__ import annotations

from services.aw_collision_financials import calculate_aw_collision_financials


AMMO_DUMP_RULE_KEY = "staff_internal_ammo_dump_500m"
# 100-300M have the same price for named/unnamed, paid fully to the worker.
# The original 500M named/unnamed margin and CS commission are unchanged.
ADDITIONAL_AMMO_DUMP_PRICES = {100: 550, 200: 1080, 300: 1620}
AMMO_DUMP_PRICES = {
    **{f"staff_internal_ammo_dump_{m}m": (price, price, price)
       for m, price in ADDITIONAL_AMMO_DUMP_PRICES.items()},
    AMMO_DUMP_RULE_KEY: (2650, 3000, 2650),
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
    return key in AMMO_DUMP_PRICES


def selected_ammo_dump_named(data: dict | None) -> bool | None:
    if not isinstance(data, dict):
        return None
    value = data.get(NAMED_SELECTION_KEY)
    # Do not silently interpret an omitted flag or strings as 'no name'.
    return value if type(value) is bool else None


def require_ammo_dump_named_selection(rule_or_key, data: dict) -> None:
    if is_internal_ammo_dump_rule(rule_or_key) and selected_ammo_dump_named(data) is None:
        raise ValueError("倒子彈請先由客服選擇「有掛名」或「無掛名」才能送出。")


def calculate_internal_ammo_dump_cs_payout(
    rule_or_key, customer_pay_amount: int | None, worker_payout_base_amount: int | None,
) -> int:
    """Only unnamed 500M orders split their 350T store margin with CS.

    Fail closed for inconsistent prices/worker bases rather than introducing
    phantom commissions on special products or damaged historical orders.
    """
    if str(getattr(rule_or_key, "key", rule_or_key) or "") != AMMO_DUMP_RULE_KEY:
        return 0
    if (
        int(customer_pay_amount or 0) == UNNAMED_PRICE
        and int(worker_payout_base_amount or 0) == WORKER_PAYOUT
    ):
        return UNNAMED_CS_PAYOUT
    return 0


def calculate_internal_ammo_dump_financials(
    price_result, data: dict, *, rule_key: str = AMMO_DUMP_RULE_KEY,
) -> dict:
    named = selected_ammo_dump_named(data)
    named_price, unnamed_price, worker_payout = AMMO_DUMP_PRICES[str(rule_key)]
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
    "ADDITIONAL_AMMO_DUMP_PRICES",
    "AMMO_DUMP_PRICES",
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
