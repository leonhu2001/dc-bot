from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from typing import Any


_BLOCKED_CATEGORIES = frozenset({"steam", "fun", "delta_desktop_fun", "title"})
_BLOCKED_RULE_KEY_TOKENS = ("teaching", "sweet")
_BLOCKED_LABEL_TOKENS = ("教學", "甜蜜")


def is_current_service_bonus(benefit: dict[str, Any] | None) -> bool:
    """Return whether this is a current seat-aware service reward.

    Historical service aliases deliberately have no seat_count and keep their
    stored snapshot behavior for in-flight/old orders.
    """

    spec = dict(benefit or {})
    if str(spec.get("kind") or "").strip().lower() != "service_bonus":
        return False
    try:
        return int(spec.get("seat_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def is_rule_service_bonus_supported(rule) -> bool:
    """Whether a formal product itself supports point-funded extra time/games.

    Point-service eligibility is intentionally narrower than generic point
    benefits: cash coupons can still be allowed on a product whose service shape
    must not be extended. Only formal hourly/game accompaniment products qualify.
    Teaching, sweet/themed, trial and fun/Steam products remain excluded.
    """

    if rule is None or not bool(getattr(rule, "point_benefits_allowed", False)):
        return False

    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
    if pricing_type not in {"hourly", "game"}:
        return False

    category = str(getattr(rule, "category", "") or "").strip().lower()
    if category in _BLOCKED_CATEGORIES:
        return False

    key = str(getattr(rule, "key", "") or "").strip().lower()
    label = str(getattr(rule, "label", "") or "").strip()
    if key.startswith("basic_trial_") or label.startswith("體驗單"):
        return False
    if any(token in key for token in _BLOCKED_RULE_KEY_TOKENS):
        return False
    if any(token in label for token in _BLOCKED_LABEL_TOKENS):
        return False

    try:
        return int(getattr(rule, "price", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def uses_rule_price_service_point_cost(rule, benefit: dict[str, Any] | None) -> bool:
    """Current service rewards always derive point cost from the formal rule."""

    return is_current_service_bonus(benefit) and is_rule_service_bonus_supported(rule)


def resolve_rule_staff_count(rule, player_count: Any = None) -> int:
    required = getattr(rule, "required_staff_count", 1)
    if required == "player_count":
        try:
            return max(1, int(player_count or 1))
        except (TypeError, ValueError):
            return 1
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return 1


def _ceil_points_to_ten(value: Decimal) -> int:
    if value <= 0:
        return 0
    return int(
        (value / Decimal("10")).to_integral_value(rounding=ROUND_CEILING)
        * Decimal("10")
    )


def calculate_rule_price_service_point_cost(
    *,
    rule,
    benefit: dict[str, Any] | None,
    player_count: Any = None,
) -> int:
    """Calculate current service-reward points from one-seat formal rule price.

    The one-seat amount is rounded up to the next 10 points first, then multiplied
    by the actual funded seat count. Non-linear checkout seat bundles therefore do
    not distort the per-companion service reward price.
    """

    spec = dict(benefit or {})
    if not uses_rule_price_service_point_cost(rule, spec):
        try:
            return max(0, int(spec.get("cost") or 0))
        except (TypeError, ValueError):
            return 0

    try:
        unit_price = max(0, int(getattr(rule, "price", 0) or 0))
    except (TypeError, ValueError):
        unit_price = 0
    if unit_price <= 0:
        return 0

    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
    bonus_size = str(spec.get("bonus_size") or "").strip().lower()
    if bonus_size not in {"small", "large"}:
        return 0

    if pricing_type == "hourly":
        service_units = Decimal("0.5") if bonus_size == "small" else Decimal("1")
    elif pricing_type == "game":
        service_units = Decimal("1") if bonus_size == "small" else Decimal("2")
    else:
        return 0

    per_seat_points = Decimal(unit_price) * service_units / Decimal("2")
    if bonus_size == "large":
        per_seat_points *= Decimal("0.9")
    rounded_per_seat = _ceil_points_to_ten(per_seat_points)

    if player_count not in (None, ""):
        seats = resolve_rule_staff_count(rule, player_count)
    else:
        try:
            seats = max(1, int(spec.get("seat_count") or 1))
        except (TypeError, ValueError):
            seats = 1
    return int(rounded_per_seat * seats)
