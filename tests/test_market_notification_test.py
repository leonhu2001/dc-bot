import json
from datetime import datetime, timedelta, timezone

import pytest

from services.market.notification_test import (
    enqueue_market_test_notification,
    split_notification_condition,
)
from services.market.personalization import MarketPersonalizationRepository
from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.push import MarketPushRepository
from services.market.push_dispatcher import _payload
from services.market.storage import MarketRepository


def _repositories(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    market.create_all()
    personalization = MarketPersonalizationRepository(market)
    personalization.create_all()
    push = MarketPushRepository(market)
    push.create_all()
    return market, personalization, push


def _store_price(market: MarketRepository, at: datetime, price: int = 5000) -> None:
    market.store_snapshot(
        MarketSourceSnapshot(
            source_name="test-tw-source",
            game_key="delta_force",
            fetched_at=at,
            source_updated_at=at,
            items=(
                MarketSourceItem(
                    source_item_id="m995",
                    name="5.56x45 M995",
                    price=price,
                    category="5.56x45",
                    tier=6,
                ),
            ),
        )
    )


def test_test_notification_uses_real_price_and_does_not_change_crossing_state(tmp_path):
    market, personalization, push = _repositories(tmp_path)
    at = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    _store_price(market, at, 5000)
    alert = personalization.create_alert(
        "user-1",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=4500,
    )

    before = personalization.list_alerts("user-1", "delta_force")[0]
    assert before.condition_met is False
    assert before.last_evaluated_at is None
    assert before.last_triggered_at is None

    event = enqueue_market_test_notification(
        market_repository=market,
        personalization_repository=personalization,
        discord_user_id="user-1",
        game_key="delta_force",
        alert_id=alert.id,
        triggered_at=at + timedelta(minutes=1),
    )

    assert event.current_price == 5000
    assert event.target_price == 4500
    assert event.condition_type == "test_below"

    pending = push.list_pending_outbox(now=at + timedelta(minutes=1))
    assert len(pending) == 1
    assert pending[0].id == event.outbox_id
    assert pending[0].condition_type == "test_below"
    assert pending[0].current_price == 5000

    after = personalization.list_alerts("user-1", "delta_force")[0]
    assert after.condition_met is False
    assert after.last_price is None
    assert after.last_evaluated_at is None
    assert after.last_triggered_at is None


def test_test_notification_is_owner_game_scoped_and_rate_limited(tmp_path):
    market, personalization, _ = _repositories(tmp_path)
    at = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    _store_price(market, at)
    alert = personalization.create_alert(
        "owner",
        "delta_force",
        "m995",
        condition_type="above",
        target_price=5500,
    )

    with pytest.raises(ValueError, match="alert not found"):
        enqueue_market_test_notification(
            market_repository=market,
            personalization_repository=personalization,
            discord_user_id="other-user",
            game_key="delta_force",
            alert_id=alert.id,
            triggered_at=at + timedelta(minutes=1),
        )

    with pytest.raises(ValueError, match="alert not found"):
        enqueue_market_test_notification(
            market_repository=market,
            personalization_repository=personalization,
            discord_user_id="owner",
            game_key="other_game",
            alert_id=alert.id,
            triggered_at=at + timedelta(minutes=1),
        )

    enqueue_market_test_notification(
        market_repository=market,
        personalization_repository=personalization,
        discord_user_id="owner",
        game_key="delta_force",
        alert_id=alert.id,
        triggered_at=at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="test notification cooldown"):
        enqueue_market_test_notification(
            market_repository=market,
            personalization_repository=personalization,
            discord_user_id="owner",
            game_key="delta_force",
            alert_id=alert.id,
            triggered_at=at + timedelta(minutes=1, seconds=10),
        )


def test_test_notification_payload_is_explicitly_marked_as_test(tmp_path):
    market, personalization, push = _repositories(tmp_path)
    at = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    _store_price(market, at, 5000)
    alert = personalization.create_alert(
        "user-1",
        "delta_force",
        "m995",
        condition_type="above",
        target_price=5500,
    )
    enqueue_market_test_notification(
        market_repository=market,
        personalization_repository=personalization,
        discord_user_id="user-1",
        game_key="delta_force",
        alert_id=alert.id,
        triggered_at=at + timedelta(minutes=1),
    )
    event = push.list_pending_outbox(now=at + timedelta(minutes=1))[0]

    payload = json.loads(_payload(event, market))
    assert payload["title"] == "🧪 價格通知測試"
    assert payload["data"]["test"] is True
    assert "現價 $5,000" in payload["body"]
    assert "目標 ≥ $5,500" in payload["body"]
    assert "已高於或等於" not in payload["body"]


def test_condition_parser_keeps_real_and_test_semantics_separate():
    assert split_notification_condition("below") == ("below", False)
    assert split_notification_condition("test_below") == ("below", True)
    assert split_notification_condition("test_above") == ("above", True)
