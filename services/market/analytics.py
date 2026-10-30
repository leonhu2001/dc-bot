from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services.market.storage import MarketRepository, StoredMarketItem, StoredMarketPoint


@dataclass(frozen=True)
class MarketItemAnalytics:
    item_key: str
    name: str
    category: str
    tier: int | None
    current_price: int
    updated_at: datetime
    change_24h_pct: float | None = None
    low_24h: int | None = None
    high_24h: int | None = None
    avg_7d: float | None = None
    low_7d: int | None = None
    high_7d: int | None = None
    history_points_7d: int = 0
    coverage_hours: float = 0.0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _change_pct(current: int, baseline: int) -> float | None:
    if current <= 0 or baseline <= 0:
        return None
    return round(((current - baseline) / baseline) * 100.0, 2)


def _stats_for_item(
    item: StoredMarketItem,
    points: tuple[StoredMarketPoint, ...],
    *,
    now: datetime,
) -> MarketItemAnalytics:
    now = _utc(now)
    updated_at = _utc(item.source_updated_at)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    window_7d = tuple(
        point
        for point in points
        if cutoff_7d <= _utc(point.source_updated_at) <= now
    )
    if not window_7d:
        window_7d = (
            StoredMarketPoint(source_updated_at=updated_at, price=item.current_price),
        )

    oldest_at = _utc(window_7d[0].source_updated_at)
    coverage_hours = max(0.0, (updated_at - oldest_at).total_seconds() / 3600.0)

    points_24h = tuple(
        point for point in window_7d if _utc(point.source_updated_at) >= cutoff_24h
    )
    prices_24h = [point.price for point in points_24h]

    # The 24H comparison uses the latest observation at/before the cutoff.
    # Do not report a percentage unless the baseline is reasonably close to
    # 24 hours ago and the current series actually spans at least 20 hours.
    baseline_candidates = tuple(
        point for point in window_7d if _utc(point.source_updated_at) <= cutoff_24h
    )
    baseline = baseline_candidates[-1] if baseline_candidates else None
    change_24h_pct: float | None = None
    if baseline is not None:
        baseline_at = _utc(baseline.source_updated_at)
        baseline_gap = (cutoff_24h - baseline_at).total_seconds()
        span_hours = (updated_at - baseline_at).total_seconds() / 3600.0
        if 0 <= baseline_gap <= 6 * 3600 and span_hours >= 20:
            change_24h_pct = _change_pct(item.current_price, baseline.price)

    # Seven-day labels only appear after at least six days of actual coverage.
    seven_day_ready = coverage_hours >= 6 * 24
    prices_7d = [point.price for point in window_7d]

    return MarketItemAnalytics(
        item_key=item.source_item_id,
        name=item.name,
        category=item.category,
        tier=item.tier,
        current_price=item.current_price,
        updated_at=updated_at,
        change_24h_pct=change_24h_pct,
        low_24h=min(prices_24h) if prices_24h else None,
        high_24h=max(prices_24h) if prices_24h else None,
        avg_7d=(round(sum(prices_7d) / len(prices_7d), 2) if seven_day_ready else None),
        low_7d=(min(prices_7d) if seven_day_ready else None),
        high_7d=(max(prices_7d) if seven_day_ready else None),
        history_points_7d=len(window_7d),
        coverage_hours=round(coverage_hours, 2),
    )


def build_market_analytics(
    repository: MarketRepository,
    game_key: str,
    *,
    latest_items: tuple[StoredMarketItem, ...] | None = None,
    now: datetime | None = None,
) -> tuple[MarketItemAnalytics, ...]:
    """Build presentation-safe analytics from persisted source history.

    The function deliberately withholds 24H/7D metrics until enough real
    history exists. This prevents a newly connected provider from presenting a
    two-hour sample as a full-day or full-week statistic.
    """
    clean_game_key = str(game_key or "").strip()
    if not clean_game_key:
        return ()

    items = latest_items if latest_items is not None else repository.list_latest(clean_game_key)
    if not items:
        return ()

    now_utc = _utc(now or datetime.now(timezone.utc))
    analytics: list[MarketItemAnalytics] = []
    for item in items:
        points = repository.history(item.item_id, limit=2000)
        analytics.append(_stats_for_item(item, points, now=now_utc))

    return tuple(analytics)
