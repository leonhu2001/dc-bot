"""Fixed store cuts for PUBLIC Delta coin-farming (not staff-internal 500M).

The gross store cut is fixed by the selected tier, independent of the
worker's previous-month bonus, named worker or store affiliation. CS receives
25% OF that cut; the remainder belongs to the store. All amounts are integer
T; 0.5T is rounded up (same as the existing unnamed internal 500M product).
"""
from __future__ import annotations

from dataclasses import dataclass

from services.aw_collision_financials import calculate_aw_collision_financials


# key: (customer-facing list price, fixed GROSS store cut)
PUBLIC_FARM_FIXED_CUTS: dict[str, tuple[int, int]] = {
    "farm_ammo_dump_100m": (800, 90),
    "farm_ammo_dump_200m": (1500, 150),
    "farm_ammo_dump_300m": (2100, 180),
    "farm_ammo_dump_500m": (3300, 200),
    "farm_ammo_dump_1000m": (6400, 400),
    "farm_ammo_dump_2000m": (11500, 600),
    "farm_car_crash_100m": (700, 80),
    "farm_car_crash_200m": (1400, 120),
    "farm_car_crash_500m": (3250, 150),
    "farm_car_crash_1000m": (6100, 300),
}
# Optional rush service is a separate selectable rule key, not an extra
# store fee. The +280T is paid in full to the assigned worker.
PUBLIC_FARM_RUSH_FEE = 280
_BASE_PUBLIC_FARM_FIXED_CUTS = dict(PUBLIC_FARM_FIXED_CUTS)
PUBLIC_FARM_FIXED_CUTS.update({
    f"{key}_rush": (price + PUBLIC_FARM_RUSH_FEE, cut)
    for key, (price, cut) in _BASE_PUBLIC_FARM_FIXED_CUTS.items()
})
CUSTOMER_SERVICE_SHARE_OF_STORE_CUT = 25  # percent


def _key(rule_or_key) -> str:
    return str(getattr(rule_or_key, "key", rule_or_key) or "").strip()


def is_public_farm_fixed_cut_rule(rule_or_key) -> bool:
    return _key(rule_or_key) in PUBLIC_FARM_FIXED_CUTS


def fixed_store_cut(rule_or_key) -> int:
    return PUBLIC_FARM_FIXED_CUTS[_key(rule_or_key)][1]


@dataclass(frozen=True)
class FarmFixedCutSettlement:
    customer_amount: int
    fixed_store_cut: int
    worker_amount: int
    customer_service_amount: int
    store_retained_amount: int


def calculate_farm_fixed_cut_settlement(
    rule_or_key, customer_amount: int, worker_amount: int | None = None,
) -> FarmFixedCutSettlement:
    key = _key(rule_or_key)
    if key not in PUBLIC_FARM_FIXED_CUTS:
        raise ValueError("這不是固定店抽的對外代肝商品。")
    paid = int(customer_amount)
    cut = fixed_store_cut(key)
    if paid < cut:
        raise ValueError(f"{key}: 顧客金額不足固定店抽，禁止套用一般分潤。")
    wages = paid - cut
    if worker_amount is not None and int(worker_amount) != wages:
        raise ValueError(f"{key}: 員工薪資基準與固定店抽不符，禁止重算。")
    cs = (cut * CUSTOMER_SERVICE_SHARE_OF_STORE_CUT + 50) // 100
    retained = cut - cs
    return FarmFixedCutSettlement(paid, cut, wages, cs, retained)


def calculate_farm_fixed_cut_financials(rule_or_key, price_result, data: dict) -> dict:
    """Bot self-service price preview: all coupons/bonuses/discounts are off."""
    key = _key(rule_or_key)
    price = int(getattr(price_result, "base_amount", 0) or 0)
    summary = calculate_farm_fixed_cut_settlement(key, price)
    finance = calculate_aw_collision_financials(price_result, {})
    finance.update(
        customer_pay_amount=summary.customer_amount,
        original_amount=summary.customer_amount,
        service_original_amount=summary.customer_amount,
        rule_original_amount=summary.customer_amount,
        priced_amount=summary.customer_amount,
        payout_base_amount=summary.worker_amount,
        store_margin_amount=summary.fixed_store_cut,
        customer_service_payout_amount=summary.customer_service_amount,
        store_retained_amount=summary.store_retained_amount,
        fixed_store_cut_policy="farm_fixed_cut_cs25_v1",
    )
    return finance


__all__ = [
    "PUBLIC_FARM_FIXED_CUTS",
    "PUBLIC_FARM_RUSH_FEE",
    "CUSTOMER_SERVICE_SHARE_OF_STORE_CUT",
    "FarmFixedCutSettlement",
    "is_public_farm_fixed_cut_rule",
    "fixed_store_cut",
    "calculate_farm_fixed_cut_settlement",
    "calculate_farm_fixed_cut_financials",
]
