from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import select

from services.market.storage import MarketItem, MarketPrice, MarketRepository, MarketSourceRun


_TAIPEI = ZoneInfo("Asia/Taipei")
_DROP_ITEM_PCT = -3.0
_BROAD_MEDIAN_PCT = -2.0
_BROAD_FALLING_RATIO = 0.35
_ISOLATED_DROP_PCT = -10.0
_ISOLATED_RESIDUAL_PCT = -8.0
_MIN_COMPARABLE_ITEMS = 20
_MIN_BROAD_CATEGORIES = 3
_MIN_PREDICTION_EVENTS = 3
_EVENT_CLUSTER_MINUTES = 90
_ACTIVE_EVENT_MINUTES = 45
_PREDICTION_BUCKET_HOURS = 2


@dataclass(frozen=True)
class MarketEventSignal:
    state: str
    label: str
    confidence: int | None = None
    compared_items: int = 0
    falling_items: int = 0
    falling_categories: int = 0
    median_change_pct: float | None = None
    historical_event_count: int = 0
    predicted_window: str | None = None
    predicted_confidence: int | None = None
    predicted_window_events: int = 0
    message: str = ""


@dataclass(frozen=True)
class _Transition:
    at: datetime
    compared_items: int
    falling_items: int
    falling_categories: int
    median_change_pct: float
    minimum_change_pct: float
    maximum_negative_residual_pct: float
    broad_drop: bool
    isolated_dump: bool


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _pct_change(previous: int, current: int) -> float:
    if previous <= 0:
        return 0.0
    return ((current - previous) / previous) * 100.0


def _transition(
    at: datetime,
    previous: dict[str, tuple[int, str]],
    current: dict[str, tuple[int, str]],
) -> _Transition | None:
    changes: list[tuple[float, str]] = []
    for item_key in previous.keys() & current.keys():
        previous_price, _previous_category = previous[item_key]
        current_price, current_category = current[item_key]
        if previous_price <= 0 or current_price <= 0:
            continue
        changes.append((_pct_change(previous_price, current_price), current_category))

    if len(changes) < 2:
        return None

    values = [value for value, _category in changes]
    market_median = float(median(values))
    falling = [(value, category) for value, category in changes if value <= _DROP_ITEM_PCT]
    falling_ratio = len(falling) / len(changes)
    categories = {category for _value, category in falling if category}
    known_categories = {category for _value, category in changes if category}
    category_breadth_ok = (
        len(known_categories) < _MIN_BROAD_CATEGORIES
        or len(categories) >= _MIN_BROAD_CATEGORIES
    )

    minimum_change = min(values)
    negative_residual = minimum_change - market_median
    broad_drop = (
        len(changes) >= _MIN_COMPARABLE_ITEMS
        and falling_ratio >= _BROAD_FALLING_RATIO
        and market_median <= _BROAD_MEDIAN_PCT
        and category_breadth_ok
    )
    isolated_dump = (
        not broad_drop
        and len(changes) >= _MIN_COMPARABLE_ITEMS
        and market_median > _BROAD_MEDIAN_PCT
        and minimum_change <= _ISOLATED_DROP_PCT
        and negative_residual <= _ISOLATED_RESIDUAL_PCT
    )

    return _Transition(
        at=_utc(at),
        compared_items=len(changes),
        falling_items=len(falling),
        falling_categories=len(categories),
        median_change_pct=round(market_median, 2),
        minimum_change_pct=round(minimum_change, 2),
        maximum_negative_residual_pct=round(negative_residual, 2),
        broad_drop=broad_drop,
        isolated_dump=isolated_dump,
    )


def _cluster_broad_events(transitions: list[_Transition]) -> list[_Transition]:
    broad = [transition for transition in transitions if transition.broad_drop]
    if not broad:
        return []

    clusters: list[list[_Transition]] = [[broad[0]]]
    gap = timedelta(minutes=_EVENT_CLUSTER_MINUTES)
    for event in broad[1:]:
        if event.at - clusters[-1][-1].at <= gap:
            clusters[-1].append(event)
        else:
            clusters.append([event])

    def event_strength(event: _Transition) -> tuple[float, float]:
        breadth = event.falling_items / max(1, event.compared_items)
        return (breadth, -event.median_change_pct)

    return [max(cluster, key=event_strength) for cluster in clusters]


def _event_confidence(event: _Transition) -> int:
    breadth = event.falling_items / max(1, event.compared_items)
    breadth_score = min(1.0, max(0.0, breadth / 0.75))
    median_score = min(1.0, abs(min(0.0, event.median_change_pct)) / 8.0)
    category_score = min(1.0, event.falling_categories / 6.0) if event.falling_categories else 0.5
    score = (breadth_score * 0.5) + (median_score * 0.35) + (category_score * 0.15)
    return max(50, min(95, round(score * 100)))


def _prediction(
    events: list[_Transition],
    *,
    now: datetime,
) -> tuple[str | None, int | None, int]:
    if len(events) < _MIN_PREDICTION_EVENTS:
        return None, None, 0

    buckets = Counter(
        (event.at.astimezone(_TAIPEI).hour // _PREDICTION_BUCKET_HOURS)
        * _PREDICTION_BUCKET_HOURS
        for event in events
    )
    bucket_start, bucket_count = buckets.most_common(1)[0]
    if bucket_count < 2:
        return None, None, bucket_count

    share = bucket_count / len(events)
    sample_factor = min(1.0, len(events) / 6.0)
    confidence = max(20, min(95, round(share * sample_factor * 100)))

    local_now = _utc(now).astimezone(_TAIPEI)
    start = local_now.replace(hour=bucket_start, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=_PREDICTION_BUCKET_HOURS)
    if local_now >= end:
        start += timedelta(days=1)
        end += timedelta(days=1)

    if start.date() == local_now.date():
        day_label = "今天"
    elif start.date() == (local_now + timedelta(days=1)).date():
        day_label = "明天"
    else:
        day_label = start.strftime("%m/%d")

    end_hour = end.astimezone(_TAIPEI).strftime("%H:%M")
    window = f"{day_label} {start.strftime('%H:%M')}–{end_hour}"
    return window, confidence, bucket_count


def analyze_market_events(
    repository: MarketRepository,
    game_key: str,
    *,
    source_name: str | None = None,
    max_snapshots: int = 672,
    now: datetime | None = None,
) -> MarketEventSignal:
    """Infer broad supply shocks and recurring low-price windows from price snapshots.

    This is intentionally probabilistic. It uses only persisted public price history;
    it does not claim to know official restock schedules, order-book depth or volume.
    """
    clean_game_key = str(game_key or "").strip()
    if not clean_game_key:
        return MarketEventSignal(state="learning", label="📊 預測學習中", message="等待行情資料。")

    clean_source_name = str(source_name or "").strip() or repository.latest_source_name(clean_game_key)
    if not clean_source_name:
        return MarketEventSignal(state="learning", label="📊 預測學習中", message="等待行情資料。")

    limit = max(2, min(int(max_snapshots), 1000))
    with repository.SessionLocal() as db:
        run_times = tuple(
            db.scalars(
                select(MarketSourceRun.source_updated_at)
                .where(
                    MarketSourceRun.game_key == clean_game_key,
                    MarketSourceRun.source_name == clean_source_name,
                )
                .order_by(MarketSourceRun.source_updated_at.desc())
                .limit(limit)
            ).all()
        )
        if len(run_times) < 2:
            return MarketEventSignal(
                state="learning",
                label="📊 預測學習中",
                message="至少需要 2 批行情才能開始判斷。",
            )

        rows = db.execute(
            select(
                MarketItem.source_item_id,
                MarketItem.category,
                MarketPrice.source_updated_at,
                MarketPrice.price,
            )
            .join(MarketPrice, MarketPrice.item_id == MarketItem.id)
            .where(
                MarketItem.game_key == clean_game_key,
                MarketItem.source_name == clean_source_name,
                MarketPrice.source_updated_at.in_(run_times),
            )
            .order_by(MarketPrice.source_updated_at.asc(), MarketItem.id.asc())
        ).all()

    snapshots: dict[datetime, dict[str, tuple[int, str]]] = {}
    for item_key, category, source_updated_at, price in rows:
        at = _utc(source_updated_at)
        snapshots.setdefault(at, {})[str(item_key)] = (int(price), str(category or ""))

    times = sorted(snapshots)
    transitions: list[_Transition] = []
    for previous_at, current_at in zip(times, times[1:]):
        event = _transition(current_at, snapshots[previous_at], snapshots[current_at])
        if event is not None:
            transitions.append(event)

    if not transitions:
        return MarketEventSignal(
            state="learning",
            label="📊 預測學習中",
            message="可比較的行情快照仍不足。",
        )

    broad_events = _cluster_broad_events(transitions)
    current_at = transitions[-1].at
    active_cutoff = current_at - timedelta(minutes=_ACTIVE_EVENT_MINUTES)
    recent_broad = [event for event in transitions if event.broad_drop and event.at >= active_cutoff]
    recent_isolated = [event for event in transitions if event.isolated_dump and event.at >= active_cutoff]

    current = transitions[-1]
    if recent_broad:
        current = recent_broad[-1]
        state = "broad_drop"
        label = "📦 疑似補貨型下跌"
        confidence = _event_confidence(current)
        message = (
            f"{current.falling_items}/{current.compared_items} 種同步下跌"
            f" · 市場中位 {current.median_change_pct:.1f}%"
        )
    elif recent_isolated:
        current = recent_isolated[-1]
        state = "isolated_dump"
        label = "🟠 單品異常拋售"
        confidence = None
        message = (
            f"市場中位 {current.median_change_pct:.1f}%"
            f" · 單品最大偏離 {current.maximum_negative_residual_pct:.1f}%"
        )
    else:
        state = "normal"
        label = "🟢 目前波動正常"
        confidence = None
        message = (
            f"最近一批 {current.falling_items}/{current.compared_items} 種跌幅達 3%"
            if current.compared_items
            else "尚無明顯市場異常。"
        )

    prediction_now = now or datetime.now(timezone.utc)
    predicted_window, predicted_confidence, bucket_events = _prediction(
        broad_events,
        now=prediction_now,
    )
    if predicted_window is None:
        learning_message = f"同步大跌樣本 {len(broad_events)}/{_MIN_PREDICTION_EVENTS}"
        if len(broad_events) >= _MIN_PREDICTION_EVENTS:
            learning_message = f"已有 {len(broad_events)} 次樣本，但時段尚未集中"
        message = f"{message} · {learning_message}"

    return MarketEventSignal(
        state=state,
        label=label,
        confidence=confidence,
        compared_items=current.compared_items,
        falling_items=current.falling_items,
        falling_categories=current.falling_categories,
        median_change_pct=current.median_change_pct,
        historical_event_count=len(broad_events),
        predicted_window=predicted_window,
        predicted_confidence=predicted_confidence,
        predicted_window_events=bucket_events,
        message=message,
    )
