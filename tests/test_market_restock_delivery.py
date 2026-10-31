from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.market.discord_delivery import MarketDiscordRepository
from services.market.personalization import MarketPersonalizationRepository
from services.market.restock_delivery import MarketRestockForecast, MarketRestockRepository
from services.market.restock_prediction import ItemRestockPrediction, _prediction_from_events
from services.market.storage import MarketRepository


def _services(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    personalization = MarketPersonalizationRepository(repository)
    personalization.create_all()
    discord = MarketDiscordRepository(repository)
    discord.create_all()
    restock = MarketRestockRepository(repository)
    restock.create_all()
    return repository, personalization, discord, restock


def _prediction(now: datetime, *, item_key: str = "m995") -> ItemRestockPrediction:
    return ItemRestockPrediction(
        item_key=item_key,
        predicted_at=now + timedelta(minutes=15),
        confidence=82,
        event_count=5,
        median_interval_minutes=360,
        jitter_minutes=10,
        last_event_at=now - timedelta(hours=6),
    )


def test_stable_item_events_produce_future_prediction():
    expected = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    events = [
        expected - timedelta(hours=18),
        expected - timedelta(hours=12),
        expected - timedelta(hours=6),
    ]

    prediction = _prediction_from_events(
        "m995",
        events,
        now=expected - timedelta(minutes=1),
    )

    assert prediction is not None
    assert prediction.predicted_at == expected
    assert prediction.confidence >= 65
    assert prediction.event_count == 3

    rolled = _prediction_from_events("m995", events, now=expected)
    assert rolled is not None
    assert rolled.predicted_at == expected + timedelta(hours=6)


def test_restock_delivery_requires_watchlist_and_dm_opt_in(tmp_path):
    _repository, personalization, discord, restock = _services(tmp_path)
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    restock.sync_predictions("delta_force", (_prediction(now),), now=now)

    assert restock.list_due_deliveries("delta_force", now=now) == ()

    personalization.set_watched("1001", "delta_force", "m995", watched=True)
    assert restock.list_due_deliveries("delta_force", now=now) == ()

    discord.set_dm_enabled("1001", True)
    due = restock.list_due_deliveries("delta_force", now=now)
    assert len(due) == 1
    assert due[0].discord_user_id == "1001"
    assert due[0].item_key == "m995"
    assert due[0].confidence == 82


def test_restock_delivery_is_deduplicated_after_send(tmp_path):
    _repository, personalization, discord, restock = _services(tmp_path)
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    personalization.set_watched("1001", "delta_force", "m995", watched=True)
    discord.set_dm_enabled("1001", True)
    restock.sync_predictions("delta_force", (_prediction(now),), now=now)

    due = restock.list_due_deliveries("delta_force", now=now)
    assert len(due) == 1
    restock.mark_sent(due[0].forecast_id, "1001")

    assert restock.list_due_deliveries("delta_force", now=now) == ()


def test_unwatching_item_stops_pending_restock_delivery(tmp_path):
    _repository, personalization, discord, restock = _services(tmp_path)
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    personalization.set_watched("1001", "delta_force", "m995", watched=True)
    discord.set_dm_enabled("1001", True)
    restock.sync_predictions("delta_force", (_prediction(now),), now=now)
    assert len(restock.list_due_deliveries("delta_force", now=now)) == 1

    personalization.set_watched("1001", "delta_force", "m995", watched=False)
    assert restock.list_due_deliveries("delta_force", now=now) == ()


def test_forecast_is_resolved_with_actual_event_for_backtest(tmp_path):
    repository, _personalization, _discord, restock = _services(tmp_path)
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    first = _prediction(now)
    restock.sync_predictions("delta_force", (first,), now=now)

    actual = first.predicted_at + timedelta(minutes=12)
    next_prediction = ItemRestockPrediction(
        item_key="m995",
        predicted_at=actual + timedelta(hours=6),
        confidence=84,
        event_count=6,
        median_interval_minutes=360,
        jitter_minutes=8,
        last_event_at=actual,
    )
    restock.sync_predictions(
        "delta_force",
        (next_prediction,),
        now=actual + timedelta(minutes=1),
    )

    with repository.SessionLocal() as db:
        rows = db.query(MarketRestockForecast).order_by(MarketRestockForecast.id.asc()).all()
    resolved = next(row for row in rows if row.status == "resolved")
    assert resolved.actual_at is not None
    assert resolved.error_minutes == 12
