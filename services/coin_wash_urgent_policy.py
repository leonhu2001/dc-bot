"""加急費只向顧客收取，100% 歸本筆訂單接單打手，不參與店家/客服抽成。"""
from __future__ import annotations

import json

URGENT_SELECTION_KEY = "coin_wash_urgent"
INTERNAL_URGENT_FEE = 260
EXTERNAL_URGENT_FEE = 280

# Internal washing has three prices: car, named ammo and unnamed ammo.
# AW collision is not washing and must never receive the washing surcharge.
INTERNAL_WASH_RULE_KEYS = frozenset({
    "staff_internal_car_500m",
    "staff_internal_ammo_dump_500m",
})
# External washing must attach only to the current car / ammo services.
# The obsolete halfcoin 120M/360M rules are strictly historical.
EXTERNAL_WASH_RULE_KEYS = frozenset({
    "farm_coin_wash_car",
    "farm_coin_wash_ammo_dump",
})


def urgent_fee_for_rule(rule_or_key) -> int:
    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()
    if key in INTERNAL_WASH_RULE_KEYS:
        return INTERNAL_URGENT_FEE
    if key in EXTERNAL_WASH_RULE_KEYS:
        return EXTERNAL_URGENT_FEE
    return 0


def selected_urgent_fee(rule_or_key, data: dict | None) -> int:
    if not isinstance(data, dict) or data.get(URGENT_SELECTION_KEY) is not True:
        return 0
    return urgent_fee_for_rule(rule_or_key)


def apply_urgent_fee(rule_or_key, data: dict, financials: dict) -> dict:
    """Add the price on top of all discounts, without changing payout basis.

    The worker gets the fee as an explicit payout bonus during web payout
    recalculation. Increasing payout_base_amount would instead give the
    ordinary 80/20 margin split, which is forbidden for this fee.
    """
    fee = selected_urgent_fee(rule_or_key, data)
    result = dict(financials)
    result["urgent_fee_amount"] = fee
    if not fee:
        return result
    for field in ("rule_original_amount", "service_original_amount",
                  "original_amount", "priced_amount", "customer_pay_amount"):
        result[field] = max(0, int(result.get(field) or 0)) + fee
    return result


def urgent_fee_from_price_snapshot(raw_snapshot) -> int:
    """Fail closed: don't accept arbitrary salary bonuses from old/invalid JSON."""
    if isinstance(raw_snapshot, dict):
        snapshot = raw_snapshot
    else:
        try:
            snapshot = json.loads(str(raw_snapshot or "{}"))
        except (ValueError, TypeError):
            return 0
    if not isinstance(snapshot, dict):
        return 0
    expected = urgent_fee_for_rule(snapshot.get("order_rule_key"))
    try:
        fee = int(snapshot.get("urgent_fee_amount") or 0)
    except (ValueError, TypeError):
        return 0
    return fee if expected and fee == expected else 0
