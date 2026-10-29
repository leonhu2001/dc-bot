from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from services.unified_service_point_policy import is_rule_service_bonus_supported


def _rule_price_table(rule) -> dict[int, int] | None:
    """Project a canonical OrderRule into its supported player-count prices.

    Explicit ``player_count_prices`` wins. Linear products such as Steam derive the
    table from the formal ``price`` + ``price_multiply_player_count`` fields instead
    of keeping another dated price dictionary in this compatibility module.
    """

    if rule is None:
        return None

    prices = dict(getattr(rule, "player_count_prices", None) or {})
    if prices:
        return {int(count): int(price) for count, price in prices.items()}

    if not bool(getattr(rule, "player_count_enabled", False)):
        return None
    if not bool(getattr(rule, "price_multiply_player_count", False)):
        return None

    try:
        unit_price = int(getattr(rule, "price", 0) or 0)
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum_raw = getattr(rule, "max_player_count", None)
        maximum = int(maximum_raw) if maximum_raw is not None else minimum
    except (TypeError, ValueError):
        return None

    if unit_price < 0 or maximum < minimum:
        return None
    return {
        count: unit_price * count
        for count in range(minimum, maximum + 1)
    }


class _CanonicalPlayerCountPriceTables(Mapping[str, dict[int, int]]):
    """Read-only compatibility view over canonical OrderRule pricing fields.

    The 2026-10-28 rollout originally duplicated price tables in this migration
    module and patched calculate_price at runtime. Formal order rules now own those
    values, so this view keeps old imports working without creating a second source
    of truth.
    """

    @staticmethod
    def _rules():
        from services.order_rules import ORDER_RULES

        return ORDER_RULES

    def __getitem__(self, key: str) -> dict[int, int]:
        table = _rule_price_table(self._rules()[str(key)])
        if not table:
            raise KeyError(key)
        return dict(table)

    def __iter__(self) -> Iterator[str]:
        for key, rule in self._rules().items():
            if _rule_price_table(rule):
                yield str(key)

    def __len__(self) -> int:
        return sum(
            1
            for rule in self._rules().values()
            if _rule_price_table(rule)
        )


PLAYER_COUNT_PRICE_TABLES: Mapping[str, dict[int, int]] = _CanonicalPlayerCountPriceTables()

# Deprecated compatibility name. Service-point eligibility is read directly from
# each formal OrderRule through unified_service_point_policy; this dict is no longer
# consulted or populated at startup.
SERVICE_POINT_BENEFIT_RULE_OVERRIDES: dict[str, bool] = {}


def get_player_count_price_table(rule_or_key) -> dict[int, int] | None:
    rule = rule_or_key if hasattr(rule_or_key, "key") else None
    if rule is None:
        try:
            from services.order_rules import ORDER_RULES

            rule = ORDER_RULES.get(str(rule_or_key or ""))
        except Exception:
            rule = None
    table = _rule_price_table(rule)
    return dict(table) if table else None


def get_rule_player_count_bounds(rule) -> tuple[int, int, int, bool]:
    """Return min, max, default and whether the customer can change the count."""
    if rule is None:
        return 1, 1, 1, False

    if bool(getattr(rule, "player_count_enabled", False)):
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum_raw = getattr(rule, "max_player_count", None)
        maximum = int(maximum_raw) if maximum_raw is not None else minimum
        maximum = max(minimum, maximum)
        return minimum, maximum, minimum, maximum > minimum

    required = getattr(rule, "required_staff_count", 1)
    try:
        fixed = max(1, int(required or 1))
    except (TypeError, ValueError):
        fixed = 1
    return fixed, fixed, fixed, False


def normalize_rule_player_count(rule, value: Any = None) -> int:
    minimum, maximum, default, _selectable = get_rule_player_count_bounds(rule)
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    if count < minimum or count > maximum:
        return default
    return count


def is_service_point_benefit_enabled(rule) -> bool:
    """Compatibility name backed by the formal product rule itself."""

    return is_rule_service_bonus_supported(rule)


def install_multi_seat_order_policy_20261028() -> None:
    """Deprecated no-op; multi-seat behavior is native to order_rules/orders."""

    return None


__all__ = [
    "PLAYER_COUNT_PRICE_TABLES",
    "SERVICE_POINT_BENEFIT_RULE_OVERRIDES",
    "get_player_count_price_table",
    "get_rule_player_count_bounds",
    "normalize_rule_player_count",
    "is_service_point_benefit_enabled",
    "install_multi_seat_order_policy_20261028",
]
