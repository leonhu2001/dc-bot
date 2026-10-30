from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class MarketSourceUnavailable(RuntimeError):
    """Raised when a configured external market source cannot be trusted/read."""


@dataclass(frozen=True)
class MarketSourceItem:
    source_item_id: str
    name: str
    price: int
    category: str = ""
    tier: int | None = None


@dataclass(frozen=True)
class MarketSourceSnapshot:
    source_name: str
    game_key: str
    fetched_at: datetime
    source_updated_at: datetime | None
    items: tuple[MarketSourceItem, ...]


class MarketPriceProvider(Protocol):
    """Adapter boundary for a game market source.

    Website, Discord and recommendation code must consume normalized snapshots
    rather than depend on a third-party endpoint or payload shape directly.
    """

    async def fetch(self, game_key: str) -> MarketSourceSnapshot:
        ...


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_source_snapshot(snapshot: MarketSourceSnapshot) -> MarketSourceSnapshot:
    """Validate and normalize a provider response before persistence.

    Invalid/non-positive prices are discarded, identifiers must be stable, and
    duplicate source IDs collapse deterministically to the last value returned
    by the provider. An empty result is treated as unavailable so a broken
    source cannot overwrite a previously healthy market state with nothing.
    """
    source_name = str(snapshot.source_name or "").strip()
    game_key = str(snapshot.game_key or "").strip()
    if not source_name:
        raise MarketSourceUnavailable("market source name is empty")
    if not game_key:
        raise MarketSourceUnavailable("market game key is empty")

    normalized: dict[str, MarketSourceItem] = {}
    for raw in snapshot.items:
        source_item_id = str(raw.source_item_id or "").strip()
        name = str(raw.name or "").strip()
        try:
            price = int(raw.price)
        except (TypeError, ValueError):
            continue

        if not source_item_id or not name or price <= 0:
            continue

        tier = raw.tier
        if tier is not None:
            try:
                tier = int(tier)
            except (TypeError, ValueError):
                tier = None
            if tier is not None and not 1 <= tier <= 10:
                tier = None

        normalized[source_item_id] = MarketSourceItem(
            source_item_id=source_item_id,
            name=name,
            price=price,
            category=str(raw.category or "").strip(),
            tier=tier,
        )

    if not normalized:
        raise MarketSourceUnavailable("market source returned no valid prices")

    fetched_at = _as_utc(snapshot.fetched_at)
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc)

    return MarketSourceSnapshot(
        source_name=source_name,
        game_key=game_key,
        fetched_at=fetched_at,
        source_updated_at=_as_utc(snapshot.source_updated_at),
        items=tuple(normalized.values()),
    )
