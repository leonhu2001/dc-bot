from __future__ import annotations


_DELTA_FORCE_GAME_KEY = "delta_force"
_DELTA_FORCE_MIN_TIER = 4


def minimum_market_tier(game_key: str) -> int | None:
    """Return the minimum tier retained for one market surface.

    Delta Force tiers 1-3 are intentionally excluded from storage, analytics,
    alert evaluation and presentation. Other games remain unscoped until they
    define their own market-tier policy.
    """
    clean_game_key = str(game_key or "").strip()
    if clean_game_key == _DELTA_FORCE_GAME_KEY:
        return _DELTA_FORCE_MIN_TIER
    return None


def market_item_enabled(game_key: str, tier: int | None) -> bool:
    minimum = minimum_market_tier(game_key)
    if minimum is None or tier is None:
        return True
    try:
        return int(tier) >= minimum
    except (TypeError, ValueError):
        return True
