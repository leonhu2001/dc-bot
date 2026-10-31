from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from services.market.analytics import build_market_analytics
from services.market.event_detector import MarketEventSignal
from services.market.event_signal_cache import get_cached_market_event_signal
from services.market.runtime import get_market_repository
from services.market.storage import MarketRepository


_RECOMMENDATION_DISCOUNT_PCT = 3.0


@dataclass(frozen=True)
class MarketItemSummary:
    item_key: str
    name: str
    current_price: int | None = None
    change_24h_pct: float | None = None
    recommendation_label: str | None = None
    category: str = ""
    tier: int | None = None
    low_24h: int | None = None
    high_24h: int | None = None
    avg_7d: float | None = None
    vs_7d_avg_pct: float | None = None
    low_7d: int | None = None
    high_7d: int | None = None
    history_points_7d: int = 0
    coverage_hours: float = 0.0


@dataclass(frozen=True)
class MarketSnapshot:
    game_key: str
    status: str
    updated_at: datetime | None = None
    recommended_item: MarketItemSummary | None = None
    items: tuple[MarketItemSummary, ...] = field(default_factory=tuple)
    gainers: tuple[MarketItemSummary, ...] = field(default_factory=tuple)
    losers: tuple[MarketItemSummary, ...] = field(default_factory=tuple)
    market_event: MarketEventSignal | None = None
    message: str = ""


def _stale_seconds() -> int:
    try:
        return max(900, int(os.getenv("MARKET_STALE_SECONDS", "2700")))
    except (TypeError, ValueError):
        return 2700


def _vs_7d_avg_pct(current_price: int | None, avg_7d: float | None) -> float | None:
    if current_price is None or avg_7d is None or avg_7d <= 0:
        return None
    return round(((current_price - avg_7d) / avg_7d) * 100.0, 2)


def _movers(items: tuple[MarketItemSummary, ...]) -> tuple[
    tuple[MarketItemSummary, ...],
    tuple[MarketItemSummary, ...],
]:
    comparable = tuple(item for item in items if item.change_24h_pct is not None)
    gainers = tuple(
        sorted(
            (item for item in comparable if (item.change_24h_pct or 0) > 0),
            key=lambda item: item.change_24h_pct or 0,
            reverse=True,
        )[:3]
    )
    losers = tuple(
        sorted(
            (item for item in comparable if (item.change_24h_pct or 0) < 0),
            key=lambda item: item.change_24h_pct or 0,
        )[:3]
    )
    return gainers, losers


def _recommended_item(items: tuple[MarketItemSummary, ...]) -> MarketItemSummary | None:
    candidates: list[tuple[float, MarketItemSummary]] = []
    for item in items:
        if item.vs_7d_avg_pct is None:
            continue
        discount_pct = -item.vs_7d_avg_pct
        if discount_pct < _RECOMMENDATION_DISCOUNT_PCT:
            continue
        candidates.append((discount_pct, item))

    if not candidates:
        return None

    discount_pct, item = max(candidates, key=lambda candidate: candidate[0])
    return replace(
        item,
        recommendation_label=f"低於 7D 均價 {discount_pct:.1f}%",
    )


def get_public_market_snapshot(
    game_key: str,
    *,
    repository: MarketRepository | None = None,
) -> MarketSnapshot:
    """Return persisted market data for website and Discord presentation."""
    clean_game_key = str(game_key or "").strip()
    if not clean_game_key:
        return MarketSnapshot(
            game_key="",
            status="source_pending",
            message="行情準備中。",
        )

    try:
        market_repository = repository or get_market_repository()
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            message="行情暫時無法使用。",
        )

    if market_repository is None:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_pending",
            message="行情準備中。",
        )

    try:
        latest = market_repository.list_latest(clean_game_key)
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            message="行情暫時無法使用。",
        )

    if not latest:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="no_data",
            message="等待第一批行情。",
        )

    updated_at = max(item.source_updated_at for item in latest)
    now = datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - updated_at).total_seconds())
    stale = age_seconds > _stale_seconds()

    try:
        analytics = build_market_analytics(
            market_repository,
            clean_game_key,
            latest_items=latest,
            now=now,
        )
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            updated_at=updated_at,
            message="行情統計暫時無法使用。",
        )

    try:
        market_event = get_cached_market_event_signal(
            market_repository,
            clean_game_key,
            source_name=latest[0].source_name,
            latest_source_at=updated_at,
            now=now,
        )
    except Exception:
        market_event = None

    items = tuple(
        MarketItemSummary(
            item_key=item.item_key,
            name=item.name,
            current_price=item.current_price,
            change_24h_pct=item.change_24h_pct,
            category=item.category,
            tier=item.tier,
            low_24h=item.low_24h,
            high_24h=item.high_24h,
            avg_7d=item.avg_7d,
            vs_7d_avg_pct=_vs_7d_avg_pct(item.current_price, item.avg_7d),
            low_7d=item.low_7d,
            high_7d=item.high_7d,
            history_points_7d=item.history_points_7d,
            coverage_hours=item.coverage_hours,
        )
        for item in analytics
    )
    gainers, losers = _movers(items)

    return MarketSnapshot(
        game_key=clean_game_key,
        status="stale" if stale else "ready",
        updated_at=updated_at,
        recommended_item=None if stale else _recommended_item(items),
        items=items,
        gainers=gainers,
        losers=losers,
        market_event=market_event,
        message="行情更新延遲，提醒暫停。" if stale else "",
    )


def filter_market_snapshot(
    snapshot: MarketSnapshot,
    *,
    query: str = "",
    tier: int | None = None,
    sort: str = "name",
) -> MarketSnapshot:
    """Filter/sort the public list without changing global mover analytics."""
    clean_query = str(query or "").strip().casefold()
    clean_tier = tier if tier in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10} else None

    items = list(snapshot.items)
    if clean_query:
        items = [
            item
            for item in items
            if clean_query in item.name.casefold()
            or clean_query in item.item_key.casefold()
            or clean_query in item.category.casefold()
        ]
    if clean_tier is not None:
        items = [item for item in items if item.tier == clean_tier]

    sort_key = str(sort or "name").strip().lower()
    if sort_key == "price_desc":
        items.sort(key=lambda item: item.current_price or -1, reverse=True)
    elif sort_key == "price_asc":
        items.sort(key=lambda item: item.current_price if item.current_price is not None else float("inf"))
    elif sort_key == "change_desc":
        items.sort(
            key=lambda item: (
                item.change_24h_pct is not None,
                item.change_24h_pct if item.change_24h_pct is not None else float("-inf"),
            ),
            reverse=True,
        )
    elif sort_key == "change_asc":
        items.sort(
            key=lambda item: (
                item.change_24h_pct is None,
                item.change_24h_pct if item.change_24h_pct is not None else float("inf"),
            )
        )
    elif sort_key == "value_asc":
        items.sort(
            key=lambda item: (
                item.vs_7d_avg_pct is None,
                item.vs_7d_avg_pct if item.vs_7d_avg_pct is not None else float("inf"),
            )
        )
    elif sort_key == "value_desc":
        items.sort(
            key=lambda item: (
                item.vs_7d_avg_pct is not None,
                item.vs_7d_avg_pct if item.vs_7d_avg_pct is not None else float("-inf"),
            ),
            reverse=True,
        )
    else:
        items.sort(key=lambda item: (item.tier is None, -(item.tier or 0), item.name.casefold()))

    return replace(snapshot, items=tuple(items))
