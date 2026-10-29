from __future__ import annotations

from typing import Any

from services.unified_service_point_policy import (
    calculate_rule_price_service_point_cost,
    is_current_service_bonus,
    is_rule_service_bonus_supported,
    uses_rule_price_service_point_cost,
)


# Canonical point redemption catalog used by both Discord self-service and web checkout.
# VIP retention / tier rewards intentionally stay out of this catalog. They belong in the
# future gift / redemption center instead of order checkout.
_POINT_SERVICE_COSTS = {
    "entertainment": {1: (80, 140), 2: (160, 280), 3: (240, 420), 4: (320, 560)},
    "technical": {1: (100, 180), 2: (200, 360), 3: (300, 540), 4: (400, 720)},
}

POINT_REDEEM_ITEMS = [
    {"key": "discount_50", "cost": 20, "name": "50T 折價券"},
    {"key": "free_specify_fee", "cost": 30, "name": "免指定費 1 次"},
    {"key": "discount_100", "cost": 45, "name": "100T 折價券"},
]
POINT_BENEFIT_SPECS = {
    "discount_50": {"kind": "cash_discount", "amount": 50, "summary": "50T 折價券，共同分攤；折後金額作為陪玩／團隊分潤基準"},
    "free_specify_fee": {"kind": "free_specify_fee", "summary": "免指定費；未實收的指定費不計入共同分潤基準"},
    "discount_100": {"kind": "cash_discount", "amount": 100, "summary": "100T 折價券，共同分攤；折後金額作為陪玩／團隊分潤基準"},
}

for tier, costs_by_seat in _POINT_SERVICE_COSTS.items():
    prefix = "entertain" if tier == "entertainment" else "tech"
    tier_text = "娛樂" if tier == "entertainment" else "技術"
    for seat_count, (small_cost, large_cost) in costs_by_seat.items():
        seat_key = {1: "single", 2: "double", 3: "triple", 4: "quad"}[seat_count]
        seat_text = "單陪" if seat_count == 1 else "雙陪" if seat_count == 2 else f"{seat_count}陪"
        for size, cost, service_text in (
            ("small", small_cost, "30 分鐘／1 局"),
            ("large", large_cost, "1 小時／2 局"),
        ):
            key = f"{prefix}_{seat_key}_service_{size}"
            POINT_REDEEM_ITEMS.append({"key": key, "cost": int(cost), "name": f"{tier_text}{seat_text}加贈｜{service_text}"})
            POINT_BENEFIT_SPECS[key] = {
                "kind": "service_bonus", "service_tier": tier, "seat_count": seat_count,
                "bonus_size": size,
                "summary": f"{tier_text}{seat_text}同步加贈 {service_text}；店內吸收全部額外服務成本",
            }


# Legacy keys remain resolvable for orders that were created before this migration.
# They are deliberately absent from POINT_REDEEM_ITEMS, so customers cannot newly select them.
LEGACY_POINT_REDEEM_ITEMS = [
    {"key": "discount_20", "cost": 10, "name": "20T 折價券"},
    {"key": "entertain_service_small", "cost": 80, "name": "娛樂陪加贈｜30 分鐘／1 局"},
    {"key": "entertain_service_large", "cost": 140, "name": "娛樂陪加贈｜1 小時／2 局"},
    {"key": "tech_service_small", "cost": 110, "name": "技術陪加贈｜30 分鐘／1 局"},
    {"key": "tech_service_large", "cost": 200, "name": "技術陪加贈｜1 小時／2 局"},
    {"key": "discount_30", "cost": 15, "name": "30T 折價券"},
    {"key": "extra_hour_30m", "cost": 60, "name": "加時 30 分鐘"},
    {"key": "extra_hour_1h", "cost": 110, "name": "加時 1 小時"},
    {"key": "extra_game_1", "cost": 40, "name": "加 1 局"},
    {"key": "extra_game_2", "cost": 70, "name": "加 2 局"},
]


LEGACY_POINT_BENEFIT_SPECS = {
    "entertain_service_small": {"kind": "service_bonus", "service_tier": "entertainment", "bonus_size": "small", "summary": "歷史娛樂陪加贈；每張僅補貼 1 位陪玩"},
    "entertain_service_large": {"kind": "service_bonus", "service_tier": "entertainment", "bonus_size": "large", "summary": "歷史娛樂陪加贈；每張僅補貼 1 位陪玩"},
    "tech_service_small": {"kind": "service_bonus", "service_tier": "technical", "bonus_size": "small", "summary": "歷史技術陪加贈；每張僅補貼 1 位陪玩"},
    "tech_service_large": {"kind": "service_bonus", "service_tier": "technical", "bonus_size": "large", "summary": "歷史技術陪加贈；每張僅補貼 1 位陪玩"},
    "discount_20": {
        "kind": "cash_discount",
        "amount": 20,
        "summary": "20T 折價券，共同分攤；折後金額作為陪玩／團隊分潤基準",
    },
    "discount_30": {
        "kind": "cash_discount",
        "amount": 30,
        "summary": "30T 折價券，共同分攤；折後金額作為陪玩／團隊分潤基準",
    },
    "extra_hour_30m": {
        "kind": "extra_hours",
        "hours": 0.5,
        "pricing_types": ("hourly",),
        "summary": "服務時間 +30 分鐘，由店內吸收額外服務成本",
    },
    "extra_hour_1h": {
        "kind": "extra_hours",
        "hours": 1,
        "pricing_types": ("hourly",),
        "summary": "服務時間 +1 小時，由店內吸收額外服務成本",
    },
    "extra_game_1": {
        "kind": "extra_games",
        "games": 1,
        "pricing_types": ("game",),
        "summary": "服務局數 +1 局，由店內吸收額外服務成本",
    },
    "extra_game_2": {
        "kind": "extra_games",
        "games": 2,
        "pricing_types": ("game",),
        "summary": "服務局數 +2 局，由店內吸收額外服務成本",
    },
}


POINT_REDEEM_ITEMS_BY_KEY = {
    item["key"]: dict(item)
    for item in POINT_REDEEM_ITEMS
}

LEGACY_POINT_REDEEM_ITEMS_BY_KEY = {
    item["key"]: dict(item)
    for item in LEGACY_POINT_REDEEM_ITEMS
}

ALL_POINT_BENEFIT_SPECS = {
    **LEGACY_POINT_BENEFIT_SPECS,
    **POINT_BENEFIT_SPECS,
}


def get_point_benefit_item(key: str | None) -> dict[str, Any] | None:
    benefit_key = str(key or "").strip()
    if not benefit_key:
        return None

    item = POINT_REDEEM_ITEMS_BY_KEY.get(benefit_key)
    if item is None:
        item = LEGACY_POINT_REDEEM_ITEMS_BY_KEY.get(benefit_key)
    if item is None:
        return None

    merged = dict(item)
    merged.update(ALL_POINT_BENEFIT_SPECS.get(benefit_key) or {})
    return merged


def get_rule_service_tier(rule) -> str | None:
    if not bool(getattr(rule, "point_benefits_allowed", False)):
        return None

    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
    if pricing_type not in {"hourly", "game"}:
        return None

    # Existing service policy already uses loyalty_benefits_enabled to mark
    # entertainment products; technical/rank services intentionally do not earn
    # the same order-count loyalty benefit. Reusing that semantic flag keeps the
    # category classification in one source of truth instead of hard-coding keys.
    if bool(getattr(rule, "loyalty_benefits_enabled", False)):
        return "entertainment"

    return "technical"


def is_service_bonus_allowed_for_rule(rule, benefit: dict[str, Any] | None, player_count: Any = None) -> bool:
    benefit = dict(benefit or {})
    if str(benefit.get("kind") or "") != "service_bonus":
        return True

    # Current seat-aware service rewards are a formal product capability. Keep the
    # eligibility decision here in the canonical catalog instead of replacing this
    # function later from dynamic_game_point_policy at process startup.
    if is_current_service_bonus(benefit) and not is_rule_service_bonus_supported(rule):
        return False

    expected_tier = str(benefit.get("service_tier") or "").strip().lower()
    if not expected_tier or expected_tier != get_rule_service_tier(rule):
        return False
    try:
        expected_seats = int(benefit.get("seat_count") or 0)
    except (TypeError, ValueError):
        expected_seats = 0
    if expected_seats <= 0:
        return True
    if getattr(rule, "required_staff_count", 1) == "player_count" and player_count in (None, ""):
        return True
    return resolve_rule_staff_count(rule, player_count) == expected_seats


def uses_dynamic_service_point_cost(rule, benefit: dict[str, Any] | None) -> bool:
    """Return whether a current service reward is priced from its formal rule."""

    return uses_rule_price_service_point_cost(rule, benefit)


def calculate_service_bonus_point_cost(
    *,
    rule,
    benefit: dict[str, Any] | None,
    player_count: Any = None,
) -> int:
    """Return authoritative point cost for a service-bonus selection.

    Current seat-aware service rewards on eligible formal hourly/game products use
    the live one-companion rule price. Historical aliases retain their stored cost.
    """

    return calculate_rule_price_service_point_cost(
        rule=rule,
        benefit=benefit,
        player_count=player_count,
    )


def adapt_point_benefit_for_rule(rule, benefit: dict[str, Any] | None) -> dict[str, Any]:
    adapted = dict(benefit or {})
    if str(adapted.get("kind") or "") != "service_bonus":
        return adapted

    # Reprice while service-bonus metadata is still intact, before converting the
    # benefit into the effective extra_hours / extra_games shape used downstream.
    adapted["cost"] = calculate_service_bonus_point_cost(
        rule=rule,
        benefit=adapted,
    )

    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
    bonus_size = str(adapted.get("bonus_size") or "").strip().lower()
    tier = str(adapted.get("service_tier") or "").strip().lower()
    try:
        seat_count = max(1, int(adapted.get("seat_count") or 1))
    except (TypeError, ValueError):
        seat_count = 1
    tier_text = "娛樂" if tier == "entertainment" else "技術"
    seat_text = "單陪" if seat_count == 1 else "雙陪" if seat_count == 2 else f"{seat_count}陪"
    benefit_text = f"{tier_text}{seat_text}"

    if pricing_type == "hourly":
        hours = 0.5 if bonus_size == "small" else 1.0
        adapted["kind"] = "extra_hours"
        adapted["hours"] = hours
        adapted["pricing_types"] = ("hourly",)
        unit_text = "30 分鐘" if abs(hours - 0.5) < 0.001 else "1 小時"
        adapted["name"] = f"{benefit_text}加贈｜{unit_text}"
        adapted["summary"] = f"服務時間 +{unit_text}，{seat_count} 位陪玩同步加贈；店內吸收全部額外服務成本"
    elif pricing_type == "game":
        games = 1 if bonus_size == "small" else 2
        adapted["kind"] = "extra_games"
        adapted["games"] = games
        adapted["pricing_types"] = ("game",)
        adapted["name"] = f"{benefit_text}加贈｜{games} 局"
        adapted["summary"] = f"服務局數 +{games} 局，{seat_count} 位陪玩同步加贈；店內吸收全部額外服務成本"

    return adapted


def resolve_rule_staff_count(rule, player_count: Any = 1) -> int:
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


def calculate_one_seat_service_bonus_value(
    *,
    rule,
    service_original: int,
    quantity: Any,
    player_count: Any,
    extra_hours: float = 0.0,
    extra_games: int = 0,
) -> int:
    try:
        quantity_value = max(1, int(quantity or 1))
    except (TypeError, ValueError):
        quantity_value = 1

    staff_count = resolve_rule_staff_count(rule, player_count)
    base_per_unit_per_seat = max(0.0, float(service_original or 0)) / quantity_value / staff_count

    if extra_hours > 0:
        return max(0, int(round(base_per_unit_per_seat * float(extra_hours))))
    if extra_games > 0:
        return max(0, int(round(base_per_unit_per_seat * int(extra_games))))
    return 0


def calculate_service_bonus_value(
    *,
    rule,
    service_original: int,
    quantity: Any,
    player_count: Any,
    extra_hours: float = 0.0,
    extra_games: int = 0,
) -> int:
    """Return the full extra-service salary value across every actual worker."""

    one_seat = calculate_one_seat_service_bonus_value(
        rule=rule,
        service_original=service_original,
        quantity=quantity,
        player_count=player_count,
        extra_hours=extra_hours,
        extra_games=extra_games,
    )
    return max(0, int(one_seat) * resolve_rule_staff_count(rule, player_count))