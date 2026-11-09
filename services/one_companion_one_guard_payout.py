from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
import json

from services.staff_internal_ammo_dump_policy import calculate_internal_ammo_dump_cs_payout
from typing import Iterable

from shared.payout import (CUSTOMER_SERVICE_PAYOUT_RATE, OrderPayoutResult,
    calculate_customer_service_payout, calculate_order_payout)


# Gross shares are one technical single + one entertainment single.
# Staff bonuses are applied afterward by shared.payout.
ONE_COMPANION_ONE_GUARD_PAYOUT_BASES: dict[str, tuple[int, int]] = {
    "basic_one_companion_one_guard_secret": (450, 350),
    "basic_one_companion_one_guard_topsecret": (500, 350),
    "basic_mobile_one_companion_one_guard_secret": (380, 320),
    "basic_mobile_one_companion_one_guard_topsecret": (420, 320),
}
# New top-secret is sold for 900T/H, but only 500+350=850T/H is
# the worker gross basis. Retain the 50T/H difference in the margin pool.
DESKTOP_ONE_GUARD_RETAIL_PRICES = {
    "basic_one_companion_one_guard_secret": 800,
    "basic_one_companion_one_guard_topsecret": 900,
}
LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES = {
    "basic_one_companion_one_guard_secret": 720,
    "basic_one_companion_one_guard_topsecret": 770,
}
LEGACY_DESKTOP_ONE_GUARD_BASES = {
    "basic_one_companion_one_guard_secret": (400, 320),
    "basic_one_companion_one_guard_topsecret": (450, 320),
}

FULL_WORKER_PAYOUT_RULE_KEYS = frozenset({
    "farm_halfcoin_120m",
    "farm_halfcoin_360m",
    "staff_internal_ammo_dump_500m",
    "staff_internal_car_500m",
    "staff_internal_aw_collision",
})
FULL_WORKER_PAYOUT_RULE_PREFIXES = ("farm_aw_collision_",)


def is_full_worker_payout_rule(rule_key: str | None) -> bool:
    key = str(rule_key or "").strip()
    return key in FULL_WORKER_PAYOUT_RULE_KEYS or key.startswith(FULL_WORKER_PAYOUT_RULE_PREFIXES)


def resolve_one_guard_unit_price(rule_key: str | None, snapshot_json: str | None) -> int | None:
    """Honor historical quote prices frozen with the order."""
    key = str(rule_key or "").strip()
    if key not in DESKTOP_ONE_GUARD_RETAIL_PRICES:
        return None
    try:
        snapshot = json.loads(str(snapshot_json or "{}"))
    except (TypeError, ValueError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        return None
    rule = snapshot.get("rule") if isinstance(snapshot.get("rule"), dict) else snapshot
    try:
        price = int(rule.get("price") or 0)
    except (ValueError, TypeError):
        return None
    return price if price in {
        DESKTOP_ONE_GUARD_RETAIL_PRICES[key],
        LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES[key],
    } else None


def payout_bases_for_rule(
    rule_key: str | None, *, unit_price: int | None = None
) -> tuple[int, int] | None:
    key = str(rule_key or "").strip()
    if (key in LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES
            and unit_price == LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES[key]):
        return LEGACY_DESKTOP_ONE_GUARD_BASES[key]
    return ONE_COMPANION_ONE_GUARD_PAYOUT_BASES.get(key)


def worker_basis_total(
    rule_key: str | None, invoice_basis: int | Decimal, *, unit_price: int | None = None
) -> Decimal:
    """Proportionally scale the worker-basis ceiling; preserves discounts."""
    key = str(rule_key or "").strip()
    total = max(Decimal(0), Decimal(str(invoice_basis or 0)))
    if key not in DESKTOP_ONE_GUARD_RETAIL_PRICES:
        return total
    bases = payout_bases_for_rule(key, unit_price=unit_price)
    if bases is None:
        return total
    retail = (LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES[key]
              if unit_price == LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES[key]
              else DESKTOP_ONE_GUARD_RETAIL_PRICES[key])
    return total * Decimal(sum(bases)) / Decimal(retail)


def _unique_worker_roles(
    worker_roles: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for worker_id, role_type in worker_roles:
        worker_id_text = str(worker_id or "").strip()
        if not worker_id_text or worker_id_text in seen:
            continue
        result.append((worker_id_text, str(role_type or "booster").strip().lower()))
        seen.add(worker_id_text)
    return result


def worker_basis_weights(
    rule_key: str | None,
    worker_roles: Iterable[tuple[str, str]],
    *, unit_price: int | None = None,
) -> dict[str, int] | None:
    """Return protector/companion gross-basis weights for the two staff slots.

    The product requires at least one protector, not exactly one. Therefore a
    protector + protector roster is valid: the first accepted protector fills
    the protector-priced slot and the second fills the companion-priced slot.
    A protector + companion roster maps naturally by role. Two companion-only
    workers are invalid for this product and return ``None``.
    """
    bases = payout_bases_for_rule(rule_key, unit_price=unit_price)
    if bases is None:
        return None

    workers = _unique_worker_roles(worker_roles)
    if len(workers) != 2:
        return None

    protector_basis, companion_basis = bases
    companions = [worker for worker in workers if worker[1] == "companion"]

    if len(companions) > 1:
        return None

    if len(companions) == 1:
        companion_id = companions[0][0]
        protector_id = next(worker_id for worker_id, _ in workers if worker_id != companion_id)
    else:
        # 護 + 護 is explicitly allowed. Acceptance order is deterministic, so
        # the first protector receives the protector slot and the second receives
        # the companion slot without increasing the total payout basis.
        protector_id = workers[0][0]
        companion_id = workers[1][0]

    return {
        protector_id: int(protector_basis),
        companion_id: int(companion_basis),
    }


def allocate_integer_gross_shares(
    rule_key: str | None,
    worker_roles: Iterable[tuple[str, str]],
    target_total: int,
    *, unit_price: int | None = None,
) -> dict[str, int] | None:
    weights = worker_basis_weights(rule_key, worker_roles, unit_price=unit_price)
    if weights is None:
        return None

    target = max(0, int(target_total or 0))
    weight_total = sum(max(0, int(value)) for value in weights.values())
    if weight_total <= 0:
        return {worker_id: 0 for worker_id in weights}

    exact = {
        worker_id: Decimal(target) * Decimal(weight) / Decimal(weight_total)
        for worker_id, weight in weights.items()
    }
    allocated = {
        worker_id: int(value.to_integral_value(rounding=ROUND_FLOOR))
        for worker_id, value in exact.items()
    }
    remainder = target - sum(allocated.values())
    order = sorted(
        exact,
        key=lambda worker_id: (
            -(exact[worker_id] - Decimal(allocated[worker_id])),
            list(weights).index(worker_id),
        ),
    )
    for worker_id in order[:remainder]:
        allocated[worker_id] += 1
    return allocated


def allocate_decimal_gross_shares(
    rule_key: str | None,
    worker_roles: Iterable[tuple[str, str]],
    target_total: Decimal,
    *, unit_price: int | None = None, scale_to_worker_basis: bool = False,
) -> dict[str, Decimal] | None:
    weights = worker_basis_weights(rule_key, worker_roles, unit_price=unit_price)
    if weights is None:
        return None

    target = max(Decimal(0), Decimal(target_total))
    if scale_to_worker_basis:
        target = worker_basis_total(rule_key, target, unit_price=unit_price)
    weight_total = sum(Decimal(max(0, int(value))) for value in weights.values())
    if weight_total <= 0:
        return {worker_id: Decimal(0) for worker_id in weights}

    return {
        worker_id: target * Decimal(weight) / weight_total
        for worker_id, weight in weights.items()
    }


def calculate_one_companion_one_guard_order_payout(
    *,
    rule_key: str | None,
    total_amount: int,
    worker_roles: Iterable[tuple[str, str]],
    named_bonus_worker_ids: list[str] | set[str] | None = None,
    customer_service_total_amount: int | None = None,
    unit_price: int | None = None,
) -> OrderPayoutResult | None:
    """Calculate normal-order payout using the product's two slot bases.

    New top-secret 900T is sold with only 850T in staff bases. Discounts
    scale each worker basis proportionally. Legacy quotes keep their old bases.
    """
    workers = _unique_worker_roles(worker_roles)

    if is_full_worker_payout_rule(rule_key):
        worker_ids = [worker_id for worker_id, _role_type in workers]
        customer_service_amount = (
            max(0, int(total_amount or 0))
            if customer_service_total_amount is None
            else max(0, int(customer_service_total_amount or 0))
        )
        payout = calculate_order_payout(
            total_amount=max(0, int(total_amount or 0)),
            worker_discord_ids=worker_ids,
            named_bonus_worker_ids=[],
            worker_base_rate=1.0,
            customer_service_rate=0.0,
            named_bonus_rate=0.0,
            customer_service_total_amount=customer_service_amount,
        )
        cs_payout = calculate_internal_ammo_dump_cs_payout(
            rule_key, customer_service_amount, total_amount
        )
        if cs_payout:
            return replace(
                payout,
                customer_service_rate=cs_payout / customer_service_amount,
                customer_service_payout=cs_payout,
                total_payout=payout.total_worker_payout + cs_payout,
            )
        return payout

    staff_basis = int(round(worker_basis_total(
        rule_key, total_amount, unit_price=unit_price
    )))
    shares = allocate_integer_gross_shares(
        rule_key, workers, staff_basis, unit_price=unit_price
    )
    if shares is None:
        return None

    customer_service_amount = (
        max(0, int(total_amount or 0))
        if customer_service_total_amount is None
        else max(0, int(customer_service_total_amount or 0))
    )
    customer_service_shares = allocate_integer_gross_shares(
        rule_key,
        workers,
        customer_service_amount,
        unit_price=unit_price,
    )
    if customer_service_shares is None:
        return None

    legacy_rate = getattr(customer_service_total_amount, "legacy_gross_rate", None)
    named_set = {
        str(worker_id)
        for worker_id in (named_bonus_worker_ids or [])
        if str(worker_id)
    }

    worker_payouts = []
    total_customer_service_payout = 0.0
    worker_base_rate = 0.0
    named_bonus_rate = 0.0

    for worker_id, _role_type in workers:
        single = calculate_order_payout(
            total_amount=int(shares[worker_id]),
            worker_discord_ids=[worker_id],
            named_bonus_worker_ids=[worker_id] if worker_id in named_set else [],
            customer_service_total_amount=int(customer_service_shares[worker_id]),
            legacy_customer_service_gross_rate=legacy_rate,
        )
        worker_payouts.extend(single.worker_payouts)
        total_customer_service_payout += float(single.customer_service_payout or 0)
        worker_base_rate = float(single.worker_base_rate or 0)
        named_bonus_rate = float(single.named_bonus_rate or 0)

    total_worker_payout = sum(float(worker.final_payout or 0) for worker in worker_payouts)
    if (str(rule_key or "") == "basic_one_companion_one_guard_topsecret"
            and unit_price != LEGACY_DESKTOP_ONE_GUARD_RETAIL_PRICES["basic_one_companion_one_guard_topsecret"]):
        # CS receives 25% of the whole actual post-worker margin, including
        # the extra 50T/H on this product. Historical gross 5% is frozen.
        if legacy_rate is not None:
            total_customer_service_payout = round(customer_service_amount * float(legacy_rate), 2)
        else:
            effective_worker_rate = (
                min(1.0, total_worker_payout / customer_service_amount)
                if customer_service_amount > 0 else 0.8
            )
            total_customer_service_payout = calculate_customer_service_payout(
                customer_service_amount, CUSTOMER_SERVICE_PAYOUT_RATE,
                effective_worker_rate=effective_worker_rate,
            )
    effective_customer_service_rate = (
        total_customer_service_payout / customer_service_amount
        if customer_service_amount > 0
        else 0.0
    )

    return OrderPayoutResult(
        total_amount=max(0, int(total_amount or 0)),
        worker_count=len(workers),
        worker_base_rate=worker_base_rate,
        customer_service_rate=effective_customer_service_rate,
        named_bonus_rate=named_bonus_rate,
        customer_service_payout=round(total_customer_service_payout, 2),
        worker_payouts=worker_payouts,
        total_worker_payout=total_worker_payout,
        total_payout=total_worker_payout + total_customer_service_payout,
    )


__all__ = [
    "ONE_COMPANION_ONE_GUARD_PAYOUT_BASES",
    "resolve_one_guard_unit_price",
    "worker_basis_total",
    "FULL_WORKER_PAYOUT_RULE_KEYS",
    "FULL_WORKER_PAYOUT_RULE_PREFIXES",
    "allocate_decimal_gross_shares",
    "allocate_integer_gross_shares",
    "calculate_one_companion_one_guard_order_payout",
    "is_full_worker_payout_rule",
    "payout_bases_for_rule",
    "worker_basis_weights",
]
