from datetime import datetime, timezone
from types import SimpleNamespace

from pywebpush import WebPushException
from requests import Response
from sqlalchemy import select

from services.market.personalization import (
    MarketNotificationOutbox,
    MarketPersonalizationRepository,
)
from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.push import (
    MarketPushDelivery,
    MarketPushRepository,
)
from services.market.push_dispatcher import WebPushConfig, dispatch_pending_pushes
from services.market.storage import MarketRepository


def _repositories(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    market.create_all()
    personalization = MarketPersonalizationRepository(market)
    personalization.create_all()
    push = MarketPushRepository(market)
    push.create_all()
    return market, personalization, push


def _seed_market(market: MarketRepository, price: int = 90) -> None:
    at = datetime.now(timezone.utc).replace(microsecond=0)
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
                    category="ammo",
                    tier=6,
                ),
            ),
        )
    )


def _trigger_outbox(personalization: MarketPersonalizationRepository, price: int = 90) -> int:
    alert = personalization.create_alert(
        "user-1",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=100,
    )
    at = datetime.now(timezone.utc).replace(microsecond=0)
    triggers = personalization.evaluate_alerts(
        "delta_force",
        {"m995": price},
        evaluated_at=at,
    )
    assert len(triggers) == 1
    with personalization.SessionLocal() as db:
        outbox_id = db.scalar(
            select(MarketNotificationOutbox.id).where(
                MarketNotificationOutbox.alert_id == alert.id
            )
        )
    assert outbox_id is not None
    return int(outbox_id)


def _config() -> WebPushConfig:
    return WebPushConfig(
        public_key="test-public-key",
        private_key="test-private-key",
        subject="mailto:test@example.com",
    )


def test_push_subscription_is_endpoint_unique_and_user_scoped(tmp_path):
    _, _, push = _repositories(tmp_path)
    endpoint = "https://push.example.test/subscription/one"

    first = push.upsert_subscription(
        "user-1",
        endpoint=endpoint,
        p256dh="p256dh-key-1",
        auth="auth-key-1",
        user_agent="test-browser",
    )
    replacement = push.upsert_subscription(
        "user-2",
        endpoint=endpoint,
        p256dh="p256dh-key-2",
        auth="auth-key-2",
        user_agent="test-browser-2",
    )

    assert replacement.id == first.id
    assert push.list_active_subscriptions("user-1") == ()
    assert [row.id for row in push.list_active_subscriptions("user-2")] == [first.id]

    assert push.unsubscribe("user-1", endpoint) is False
    assert push.unsubscribe("user-2", endpoint) is True
    assert push.list_active_subscriptions("user-2") == ()


def test_dispatch_sends_each_device_once_and_marks_outbox_sent(tmp_path, monkeypatch):
    market, personalization, push = _repositories(tmp_path)
    _seed_market(market)
    outbox_id = _trigger_outbox(personalization)
    first = push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/one",
        p256dh="p256dh-one",
        auth="auth-one",
    )
    second = push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/two",
        p256dh="p256dh-two",
        auth="auth-two",
    )

    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr("services.market.push_dispatcher.webpush", fake_webpush)

    summary = dispatch_pending_pushes(
        market_repository=market,
        push_repository=push,
        config=_config(),
    )
    assert summary.processed == 1
    assert summary.sent == 1
    assert summary.retried == 0
    assert len(calls) == 2
    assert {call["subscription_info"]["endpoint"] for call in calls} == {
        first.endpoint,
        second.endpoint,
    }

    with push.SessionLocal() as db:
        outbox = db.get(MarketNotificationOutbox, outbox_id)
        deliveries = db.scalars(
            select(MarketPushDelivery).where(MarketPushDelivery.outbox_id == outbox_id)
        ).all()
        assert outbox is not None
        assert outbox.status == "sent"
        assert outbox.sent_at is not None
        assert len(deliveries) == 2
        assert {delivery.status for delivery in deliveries} == {"success"}

    second_summary = dispatch_pending_pushes(
        market_repository=market,
        push_repository=push,
        config=_config(),
    )
    assert second_summary.processed == 0
    assert len(calls) == 2


def test_dispatch_transient_error_retries_with_backoff(tmp_path, monkeypatch):
    market, personalization, push = _repositories(tmp_path)
    _seed_market(market)
    outbox_id = _trigger_outbox(personalization)
    push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/retry",
        p256dh="p256dh-retry",
        auth="auth-retry",
    )

    def failing_webpush(**_kwargs):
        raise RuntimeError("temporary transport failure")

    monkeypatch.setattr("services.market.push_dispatcher.webpush", failing_webpush)
    before = datetime.now(timezone.utc)
    summary = dispatch_pending_pushes(
        market_repository=market,
        push_repository=push,
        config=_config(),
    )

    assert summary.processed == 1
    assert summary.retried == 1
    with push.SessionLocal() as db:
        outbox = db.get(MarketNotificationOutbox, outbox_id)
        delivery = db.scalar(
            select(MarketPushDelivery).where(MarketPushDelivery.outbox_id == outbox_id)
        )
        assert outbox is not None
        assert outbox.status == "pending"
        assert outbox.attempts == 1
        available_at = outbox.available_at
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=timezone.utc)
        assert available_at > before
        assert delivery is not None
        assert delivery.status == "retry"


def test_dispatch_expired_endpoint_disables_subscription(tmp_path, monkeypatch):
    market, personalization, push = _repositories(tmp_path)
    _seed_market(market)
    outbox_id = _trigger_outbox(personalization)
    subscription = push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/expired",
        p256dh="p256dh-expired",
        auth="auth-expired",
    )

    def expired_webpush(**_kwargs):
        response = Response()
        response.status_code = 410
        raise WebPushException("gone", response=response)

    monkeypatch.setattr("services.market.push_dispatcher.webpush", expired_webpush)
    summary = dispatch_pending_pushes(
        market_repository=market,
        push_repository=push,
        config=_config(),
    )

    assert summary.processed == 1
    assert summary.no_subscription == 1
    assert push.list_active_subscriptions("user-1") == ()
    with push.SessionLocal() as db:
        outbox = db.get(MarketNotificationOutbox, outbox_id)
        delivery = db.scalar(
            select(MarketPushDelivery).where(
                MarketPushDelivery.outbox_id == outbox_id,
                MarketPushDelivery.subscription_id == subscription.id,
            )
        )
        assert outbox is not None
        assert outbox.status == "no_subscription"
        assert delivery is not None
        assert delivery.status == "expired"
        assert delivery.response_status == 410
