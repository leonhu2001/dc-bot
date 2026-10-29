from __future__ import annotations

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
