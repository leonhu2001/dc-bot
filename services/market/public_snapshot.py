from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from services.market.analytics import build_market_analytics
from services.market.event_detector import MarketEventSignal
from services.market.event_signal_cache import get_cached_market_event_signal
from services.market.restock_prediction import (
    ItemRestockPrediction,
    get_cached_item_restock_predictions,
)
from services.market.runtime import get_market_repository
from services.market.scope import market_item_enabled
from services.market.storage import MarketRepository


_RECOMMENDATION_DISCOUNT_PCT = 3.0
_TAIPEI = ZoneInfo("Asia/Taipei")


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
    restock_predicted_at: datetime | None = None
    restock_prediction_label: str | None = None
    restock_confidence: int | None = None
    restock_event_count: int = 0
    restock_jitter_minutes: int | None = None


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
    next_restock_item: MarketItemSummary | None = None
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


def _restock_prediction_label(predicted_at: datetime, *, now: datetime) -> str:
    local_predicted = predicted_at.astimezone(_TAIPEI)
    local_now = now.astimezone(_TAIPEI)
    day_delta = (local_predicted.date() - local_now.date()).days
    if day_delta == 0:
        prefix = "今天"
    elif day_delta == 1:
        prefix = "明天"
    elif day_delta == 2:
        prefix = "後天"
    else:
        prefix = f"{local_predicted.month}/{local_predicted.day}"
    return f"{prefix} {local_predicted.strftime('%H:%M')}"


def _with_restock_prediction(
    item: MarketItemSummary,
    prediction: ItemRestockPrediction | None,
    *,
    now: datetime,
) -> MarketItemSummary:
    if prediction is None:
        return item
    return replace(
        item,
        restock_predicted_at=prediction.predicted_at,
        restock_prediction_label=_restock_prediction_label(
            prediction.predicted_at,
            now=now,
        ),
        restock_confidence=prediction.confidence,
        restock_event_count=prediction.event_count,
        restock_jitter_minutes=prediction.jitter_minutes,
    )


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


def _next_restock_item(items: tuple[MarketItemSummary, ...]) -> MarketItemSummary | None:
    predicted = tuple(item for item in items if item.restock_predicted_at is not None)
    if not predicted:
        return None
    return min(
        predicted,
        key=lambda item: (
            item.restock_predicted_at or datetime.max.replace(tzinfo=timezone.utc),
            -(item.restock_confidence or 0),
            item.name.casefold(),
        ),
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
        raw_latest = market_repository.list_latest(clean_game_key)
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            message="行情暫時無法使用。",
        )

    if not raw_latest:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="no_data",
            message="等待第一批行情。",
        )

    latest = tuple(
        item
        for item in raw_latest
        if market_item_enabled(clean_game_key, item.tier)
    )
    if not latest:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="no_data",
            message="等待可用行情。",
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

    try:
        restock_predictions = get_cached_item_restock_predictions(
            market_repository,
            clean_game_key,
            now=now,
        )
    except Exception:
        restock_predictions = ()
    restock_by_item = {
        prediction.item_key: prediction
        for prediction in restock_predictions
    }

    items = tuple(
        _with_restock_prediction(
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
            ),
            restock_by_item.get(item.item_key),
            now=now,
        )
        for item in analytics
        if market_item_enabled(clean_game_key, item.tier)
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
        next_restock_item=None if stale else _next_restock_item(items),
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
    requested_tier = tier if tier in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10} else None
    blocked_tier = requested_tier is not None and not market_item_enabled(
        snapshot.game_key,
        requested_tier,
    )
    clean_tier = requested_tier if not blocked_tier else -1

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
    elif sort_key == "restock_asc":
        items.sort(
            key=lambda item: (
                item.restock_predicted_at is None,
                item.restock_predicted_at or datetime.max.replace(tzinfo=timezone.utc),
                -(item.restock_confidence or 0),
            )
        )
    else:
        items.sort(key=lambda item: (item.tier is None, -(item.tier or 0), item.name.casefold()))

    return replace(snapshot, items=tuple(items))
