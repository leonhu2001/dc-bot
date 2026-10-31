from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from services.market.discord_delivery import MarketDiscordRepository
from services.market.personalization import (
    MarketNotificationOutbox,
    MarketPersonalizationRepository,
)
from services.market.storage import MarketRepository


def _repositories(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    market.create_all()
    personalization = MarketPersonalizationRepository(market)
    personalization.create_all()
    discord_repo = MarketDiscordRepository(market)
    discord_repo.create_all()
    return market, personalization, discord_repo


def test_discord_dm_is_explicit_opt_in(tmp_path):
    _, _, discord_repo = _repositories(tmp_path)

    enabled, enabled_at = discord_repo.dm_state("123")
    assert enabled is False
    assert enabled_at is None

    assert discord_repo.set_dm_enabled("123", True) is True
    enabled, enabled_at = discord_repo.dm_state("123")
    assert enabled is True
    assert enabled_at is not None

    assert discord_repo.set_dm_enabled("123", False) is False
    assert discord_repo.dm_enabled("123") is False


def test_discord_delivery_does_not_compete_with_web_push_outbox_status(tmp_path):
    _, personalization, discord_repo = _repositories(tmp_path)
    alert = personalization.create_alert(
        "123",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=100,
    )
    triggered_at = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)
    personalization.evaluate_alerts(
        "delta_force",
        {"m995": 90},
        evaluated_at=triggered_at,
    )

    # Simulate Web Push completing first. Discord must still consume the same
    # durable crossing event using its own delivery table.
    with personalization.SessionLocal() as db:
        db.execute(
            update(MarketNotificationOutbox)
            .where(MarketNotificationOutbox.alert_id == alert.id)
            .values(
                status="sent",
                sent_at=triggered_at + timedelta(seconds=5),
            )
        )
        db.commit()

    pending = discord_repo.list_pending_events()
    assert len(pending) == 1
    assert pending[0].alert_id == alert.id
    assert pending[0].current_price == 90

    discord_repo.mark_sent(pending[0].outbox_id)
    assert discord_repo.list_pending_events() == ()


def test_cancelled_shared_outbox_is_not_sent_to_discord(tmp_path):
    _, personalization, discord_repo = _repositories(tmp_path)
    alert = personalization.create_alert(
        "123",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=100,
    )
    personalization.evaluate_alerts(
        "delta_force",
        {"m995": 90},
        evaluated_at=datetime.now(timezone.utc),
    )

    assert personalization.set_alert_enabled("123", alert.id, enabled=False) is True
    assert discord_repo.list_pending_events() == ()


def test_discord_retry_is_bounded_and_does_not_repeat_sent_event(tmp_path):
    _, personalization, discord_repo = _repositories(tmp_path)
    personalization.create_alert(
        "123",
        "delta_force",
        "m995",
        condition_type="above",
        target_price=100,
    )
    personalization.evaluate_alerts(
        "delta_force",
        {"m995": 120},
        evaluated_at=datetime.now(timezone.utc),
    )
    event = discord_repo.list_pending_events()[0]

    discord_repo.mark_retry(event.outbox_id, reason="HTTP 503", max_attempts=2)
    assert discord_repo.list_pending_events() == ()

    # Make the retry due, then exhaust it. Failed is terminal for Discord only.
    with discord_repo.SessionLocal() as db:
        row = db.get(__import__(
            "services.market.discord_delivery",
            fromlist=["MarketDiscordDelivery"],
        ).MarketDiscordDelivery, event.outbox_id)
        row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    retry = discord_repo.list_pending_events()
    assert len(retry) == 1
    discord_repo.mark_retry(event.outbox_id, reason="HTTP 503", max_attempts=2)
    assert discord_repo.list_pending_events() == ()
