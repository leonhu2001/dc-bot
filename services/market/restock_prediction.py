from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from threading import Lock
from time import monotonic

from sqlalchemy import select

from services.market.event_detector import _cluster_broad_events, _transition
from services.market.scope import minimum_market_tier
from services.market.storage import MarketItem, MarketPrice, MarketRepository, MarketSourceRun


_MIN_ITEM_EVENTS = 3
_MIN_INTERVAL_MINUTES = 90
_MAX_INTERVAL_MINUTES = 72 * 60
_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class ItemRestockPrediction:
    item_key: str
    predicted_at: datetime
    confidence: int
    event_count: int
    median_interval_minutes: int
    jitter_minutes: int
    last_event_at: datetime


_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, datetime | None, tuple[ItemRestockPrediction, ...]]] = {}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _round_five_minutes(value: datetime) -> datetime:
    at = _utc(value)
    minute = int(round(at.minute / 5.0) * 5)
    if minute >= 60:
        at = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        at = at.replace(minute=minute, second=0, microsecond=0)
    return at


def _prediction_from_events(
    item_key: str,
    events: list[datetime],
    *,
    now: datetime,
) -> ItemRestockPrediction | None:
    ordered = sorted({_utc(value) for value in events})
    if len(ordered) < _MIN_ITEM_EVENTS:
        return None

    intervals = [
        (right - left).total_seconds() / 60.0
        for left, right in zip(ordered, ordered[1:])
    ]
    intervals = [
        value
        for value in intervals
        if _MIN_INTERVAL_MINUTES <= value <= _MAX_INTERVAL_MINUTES
    ]
    if len(intervals) < 2:
        return None

    interval_median = float(median(intervals))
    deviations = [abs(value - interval_median) for value in intervals]
    jitter = float(median(deviations)) if deviations else 0.0

    tolerance = max(30.0, interval_median * 0.25)
    consistency = max(0.0, min(1.0, 1.0 - (jitter / tolerance)))
    sample_score = min(1.0, max(0.0, (len(ordered) - 2) / 4.0))
    confidence = max(50, min(95, round(55 + (30 * consistency) + (10 * sample_score))))

    predicted = ordered[-1] + timedelta(minutes=interval_median)
    clean_now = _utc(now)
    # Never invent another cycle after a prediction has already been missed.
    # A new forecast requires a newly observed broad restock-type event.
    if predicted <= clean_now:
        return None

    return ItemRestockPrediction(
        item_key=str(item_key),
        predicted_at=_round_five_minutes(predicted),
        confidence=confidence,
        event_count=len(ordered),
        median_interval_minutes=max(1, round(interval_median)),
        jitter_minutes=max(0, round(jitter)),
        last_event_at=ordered[-1],
    )


def predict_item_restocks(
    repository: MarketRepository,
    game_key: str,
    *,
    source_name: str | None = None,
    max_snapshots: int = 672,
    now: datetime | None = None,
) -> tuple[ItemRestockPrediction, ...]:
    clean_game = str(game_key or "").strip()
    if not clean_game:
        return ()

    clean_source = str(source_name or "").strip() or repository.latest_source_name(clean_game)
    if not clean_source:
        return ()

    limit = max(8, min(int(max_snapshots), 1000))
    with repository.SessionLocal() as db:
        run_times = tuple(
            db.scalars(
                select(MarketSourceRun.source_updated_at)
                .where(
                    MarketSourceRun.game_key == clean_game,
                    MarketSourceRun.source_name == clean_source,
                )
                .order_by(MarketSourceRun.source_updated_at.desc())
                .limit(limit)
            ).all()
        )
        if len(run_times) < 4:
            return ()

        rows_query = (
            select(
                MarketItem.source_item_id,
                MarketItem.category,
                MarketPrice.source_updated_at,
                MarketPrice.price,
            )
            .join(MarketPrice, MarketPrice.item_id == MarketItem.id)
            .where(
                MarketItem.game_key == clean_game,
                MarketItem.source_name == clean_source,
                MarketPrice.source_updated_at.in_(run_times),
            )
        )
        minimum_tier = minimum_market_tier(clean_game)
        if minimum_tier is not None:
            rows_query = rows_query.where(
                MarketItem.tier.is_(None) | (MarketItem.tier >= minimum_tier)
            )
        rows = db.execute(
            rows_query.order_by(
                MarketPrice.source_updated_at.asc(),
                MarketItem.id.asc(),
            )
        ).all()

    snapshots: dict[datetime, dict[str, tuple[int, str]]] = {}
    for item_key, category, source_updated_at, price in rows:
        at = _utc(source_updated_at)
        snapshots.setdefault(at, {})[str(item_key)] = (int(price), str(category or ""))

    times = sorted(snapshots)
    transitions = []
    for previous_at, current_at in zip(times, times[1:]):
        transition = _transition(
            current_at,
            snapshots[previous_at],
            snapshots[current_at],
        )
        if transition is not None:
            transitions.append(transition)

    broad_events = _cluster_broad_events(transitions)
    if not broad_events:
        return ()

    item_events: dict[str, list[datetime]] = {}
    for event in broad_events:
        for item_key, change_pct in event.item_changes:
            if change_pct <= -3.0:
                item_events.setdefault(str(item_key), []).append(event.at)

    clean_now = _utc(now or datetime.now(timezone.utc))
    predictions = [
        prediction
        for item_key, events in item_events.items()
        if (prediction := _prediction_from_events(item_key, events, now=clean_now)) is not None
    ]
    predictions.sort(key=lambda row: (row.predicted_at, -row.confidence, row.item_key))
    return tuple(predictions)


def get_cached_item_restock_predictions(
    repository: MarketRepository,
    game_key: str,
    *,
    now: datetime | None = None,
) -> tuple[ItemRestockPrediction, ...]:
    clean_game = str(game_key or "").strip()
    if not clean_game:
        return ()

    try:
        latest = repository.list_latest(clean_game, limit=500)
        latest_at = max((item.source_updated_at for item in latest), default=None)
        latest_at = _utc(latest_at) if latest_at is not None else None
    except Exception:
        latest_at = None

    stamp = monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(clean_game)
        if cached is not None:
            cached_at, cached_source_at, rows = cached
            if cached_source_at == latest_at and stamp - cached_at < _CACHE_TTL_SECONDS:
                return rows

    rows = predict_item_restocks(repository, clean_game, now=now)
    with _CACHE_LOCK:
        _CACHE[clean_game] = (stamp, latest_at, rows)
    return rows


def clear_restock_prediction_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
