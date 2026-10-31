from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from services.market.event_detector import MarketEventSignal, analyze_market_events
from services.market.storage import MarketRepository


_TAIPEI = ZoneInfo("Asia/Taipei")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@lru_cache(maxsize=64)
def _cached_market_event_signal(
    repository: MarketRepository,
    game_key: str,
    source_name: str,
    latest_source_at: datetime,
    prediction_clock_hour: datetime,
) -> MarketEventSignal:
    # latest_source_at is intentionally part of the cache key. A new persisted
    # market snapshot invalidates the previous inference immediately. The hour
    # key refreshes relative "today / tomorrow" prediction copy even if a source
    # becomes temporarily stale.
    _ = latest_source_at
    return analyze_market_events(
        repository,
        game_key,
        source_name=source_name,
        now=prediction_clock_hour,
    )


def get_cached_market_event_signal(
    repository: MarketRepository,
    game_key: str,
    *,
    source_name: str,
    latest_source_at: datetime,
    now: datetime | None = None,
) -> MarketEventSignal:
    clock = _utc(now or datetime.now(timezone.utc)).astimezone(_TAIPEI)
    clock_hour = clock.replace(minute=0, second=0, microsecond=0)
    return _cached_market_event_signal(
        repository,
        str(game_key or "").strip(),
        str(source_name or "").strip(),
        _utc(latest_source_at),
        clock_hour,
    )
