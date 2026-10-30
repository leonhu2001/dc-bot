from __future__ import annotations

import os
from collections.abc import Callable

from services.market.providers.base import MarketPriceProvider
from services.market.providers.public_852941 import Public852941Provider


ProviderFactory = Callable[[], MarketPriceProvider]
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "852941-tw": Public852941Provider,
}


def register_market_provider(name: str, factory: ProviderFactory) -> None:
    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("market provider name is required")
    _PROVIDER_FACTORIES[key] = factory


def configured_provider_name() -> str:
    return os.getenv("MARKET_PROVIDER", "").strip().lower()


def build_configured_provider() -> MarketPriceProvider | None:
    """Build only an explicitly configured, registered market provider.

    There is deliberately no automatic fallback to a different region/source.
    A missing Taiwan/Garena source must remain visibly unavailable rather than
    silently switching to unrelated market prices.
    """
    key = configured_provider_name()
    if not key:
        return None

    factory = _PROVIDER_FACTORIES.get(key)
    if factory is None:
        known = ", ".join(sorted(_PROVIDER_FACTORIES)) or "none"
        raise RuntimeError(
            f"unknown MARKET_PROVIDER '{key}' (registered providers: {known})"
        )
    return factory()
