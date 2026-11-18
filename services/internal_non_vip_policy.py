"""Canonical VIP/reward exclusion for internal employee orders.

Apply by immutable SKU as well as the staff_internal category so a historical
ticket alias, renamed UI label, or Web -> Bot sync cannot award VIP spend.
Never exclude public farm coin washing or public AW orders.
"""

INTERNAL_NO_VIP_RULE_KEYS = frozenset({
    "staff_internal_ammo_dump_100m",
    "staff_internal_ammo_dump_200m",
    "staff_internal_ammo_dump_300m",
    "staff_internal_ammo_dump_500m",
    "staff_internal_car_500m",
    "staff_internal_aw_collision",
})

INTERNAL_NO_VIP_REASON = "員工內部洗幣／AW 代撞不累積 VIP 消費與消費點數"


def is_internal_non_vip_order(order_data: dict | None) -> bool:
    if not isinstance(order_data, dict):
        return False
    key = str(order_data.get("order_rule_key") or "").strip()
    category = str(order_data.get("category") or "").strip().lower()
    return key in INTERNAL_NO_VIP_RULE_KEYS or category == "staff_internal"
