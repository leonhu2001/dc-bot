from __future__ import annotations

from dataclasses import dataclass, replace

from services.market.providers.base import MarketPriceProvider, normalize_source_snapshot
from services.market.scope import market_item_enabled
from services.market.storage import MarketRepository


@dataclass(frozen=True)
class MarketIngestResult:
    game_key: str
    source_name: str
    item_count: int
    inserted_price_count: int
    duplicate_snapshot: bool


async def ingest_market_snapshot(
    *,
    provider: MarketPriceProvider,
    repository: MarketRepository,
    game_key: str,
) -> MarketIngestResult:
    """Fetch, validate and persist one provider snapshot.

    Source-specific HTTP/parsing logic stays in the provider. This coordinator
    is intentionally small so a future worker can call it on a schedule without
    duplicating validation or persistence rules.
    """
    snapshot = normalize_source_snapshot(await provider.fetch(game_key))
    tracked_items = tuple(
        item
        for item in snapshot.items
        if market_item_enabled(snapshot.game_key, item.tier)
    )
    snapshot = replace(snapshot, items=tracked_items)
    inserted = repository.store_snapshot(snapshot)

    return MarketIngestResult(
        game_key=snapshot.game_key,
        source_name=snapshot.source_name,
        item_count=len(snapshot.items),
        inserted_price_count=inserted,
        duplicate_snapshot=(inserted == 0),
    )
