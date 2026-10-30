from __future__ import annotations

import os
from functools import lru_cache

from services.market.storage import MarketRepository


@lru_cache(maxsize=1)
def get_market_repository() -> MarketRepository | None:
    """Return the optional independent market repository.

    Market storage is deliberately opt-in. Existing Bot/Web/order startup must
    remain healthy when MARKET_DATABASE_URL has not been provisioned yet.
    """
    database_url = os.getenv("MARKET_DATABASE_URL", "").strip()
    if not database_url:
        return None

    repository = MarketRepository(database_url)
    repository.create_all()
    return repository


def reset_market_repository_cache() -> None:
    """Test/deploy helper after MARKET_DATABASE_URL changes."""
    get_market_repository.cache_clear()
