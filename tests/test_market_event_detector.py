from datetime import datetime, timedelta, timezone

from services.market.event_detector import analyze_market_events
from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.storage import MarketRepository


ITEM_COUNT = 30


def _repository(tmp_path) -> MarketRepository:
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market-events.db'}")
    repository.create_all()
    return repository


def _store(repository: MarketRepository, at: datetime, prices: list[int]) -> None:
    repository.store_snapshot(
        MarketSourceSnapshot(
            source_name="test-source",
            game_key="delta_force",
            fetched_at=at,
            source_updated_at=at,
            items=tuple(
                MarketSourceItem(
                    source_item_id=f"ammo-{index:02d}",
                    name=f"Ammo {index:02d}",
                    price=price,
                    category=f"caliber-{index % 6}",
                    tier=5 if index % 2 else 6,
                )
                for index, price in enumerate(prices)
            ),
        )
    )


def _prices(value: int) -> list[int]:
    return [value for _ in range(ITEM_COUNT)]


def test_synchronized_market_drop_is_classified_as_broad_supply_event(tmp_path):
    repository = _repository(tmp_path)
    start = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
    _store(repository, start, _prices(100))
    _store(repository, start + timedelta(minutes=15), _prices(90))

    signal = analyze_market_events(repository, "delta_force")

    assert signal.state == "broad_drop"
    assert signal.label == "📦 疑似補貨型下跌"
    assert signal.compared_items == ITEM_COUNT
    assert signal.falling_items == ITEM_COUNT
    assert signal.falling_categories == 6
    assert signal.median_change_pct == -10.0
    assert signal.confidence is not None
    assert signal.confidence >= 50


def test_single_item_crash_with_stable_market_is_classified_as_isolated_dump(tmp_path):
    repository = _repository(tmp_path)
    start = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
    _store(repository, start, _prices(100))
    changed = _prices(100)
    changed[0] = 80
    _store(repository, start + timedelta(minutes=15), changed)

    signal = analyze_market_events(repository, "delta_force")

    assert signal.state == "isolated_dump"
    assert signal.label == "🟠 單品異常拋售"
    assert signal.median_change_pct == 0.0
    assert signal.falling_items == 1
    assert signal.confidence is None


def test_small_market_move_remains_normal(tmp_path):
    repository = _repository(tmp_path)
    start = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
    _store(repository, start, _prices(100))
    _store(repository, start + timedelta(minutes=15), _prices(99))

    signal = analyze_market_events(repository, "delta_force")

    assert signal.state == "normal"
    assert signal.label == "🟢 目前波動正常"
    assert signal.falling_items == 0
    assert signal.predicted_window is None


def test_repeated_evening_broad_drops_predict_next_taipei_low_price_window(tmp_path):
    repository = _repository(tmp_path)
    first_day = datetime(2026, 10, 28, 9, 50, tzinfo=timezone.utc)  # 17:50 Taipei

    for day in range(3):
        baseline_at = first_day + timedelta(days=day)
        drop_at = baseline_at + timedelta(minutes=20)  # 18:10 Taipei
        _store(repository, baseline_at, _prices(100))
        _store(repository, drop_at, _prices(90))

    signal = analyze_market_events(
        repository,
        "delta_force",
        now=datetime(2026, 10, 30, 12, 30, tzinfo=timezone.utc),  # 20:30 Taipei
    )

    assert signal.historical_event_count == 3
    assert signal.predicted_window == "明天 18:00–20:00"
    assert signal.predicted_window_events == 3
    assert signal.predicted_confidence == 50


def test_prediction_waits_for_three_broad_drop_samples(tmp_path):
    repository = _repository(tmp_path)
    first_day = datetime(2026, 10, 29, 9, 50, tzinfo=timezone.utc)

    for day in range(2):
        baseline_at = first_day + timedelta(days=day)
        _store(repository, baseline_at, _prices(100))
        _store(repository, baseline_at + timedelta(minutes=20), _prices(90))

    signal = analyze_market_events(repository, "delta_force")

    assert signal.historical_event_count == 2
    assert signal.predicted_window is None
    assert signal.predicted_confidence is None
    assert "同步大跌樣本 2/3" in signal.message
