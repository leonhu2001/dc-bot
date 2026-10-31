from __future__ import annotations


_DELTA_FORCE_GAME_KEY = "delta_force"
_DELTA_FORCE_MIN_TIER = 4
_DELTA_FORCE_MAX_TIER = 5


def minimum_market_tier(game_key: str) -> int | None:
    """Return the minimum tier retained for one market surface."""
    clean_game_key = str(game_key or "").strip()
    if clean_game_key == _DELTA_FORCE_GAME_KEY:
        return _DELTA_FORCE_MIN_TIER
    return None


def maximum_market_tier(game_key: str) -> int | None:
    """Return the maximum tier retained for one market surface."""
    clean_game_key = str(game_key or "").strip()
    if clean_game_key == _DELTA_FORCE_GAME_KEY:
        return _DELTA_FORCE_MAX_TIER
    return None


def market_item_enabled(game_key: str, tier: int | None) -> bool:
    """Whether an item belongs to the active price-tracking scope.

    Delta Force only tracks tradable tier 4-5 ammunition. Tiers 1-3 and tier 6+
    are excluded from storage, analytics, alert evaluation, prediction and web
    presentation. Other games remain unscoped until they define their own
    market-tier policy.
    """
    if tier is None:
        return True

    try:
        clean_tier = int(tier)
    except (TypeError, ValueError):
        return True

    minimum = minimum_market_tier(game_key)
    maximum = maximum_market_tier(game_key)
    if minimum is not None and clean_tier < minimum:
        return False
    if maximum is not None and clean_tier > maximum:
        return False
    return True
