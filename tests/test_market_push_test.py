import json
from types import SimpleNamespace

from pywebpush import WebPushException
from requests import Response

from services.market.push import MarketPushRepository
from services.market.push_dispatcher import WebPushConfig
from services.market.push_test import send_test_push
from services.market.storage import MarketRepository


def _push_repository(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    market.create_all()
    push = MarketPushRepository(market)
    push.create_all()
    return push


def _config() -> WebPushConfig:
    return WebPushConfig(
        public_key="test-public-key",
        private_key="test-private-key",
        subject="mailto:test@example.com",
    )


def test_send_test_push_targets_one_subscription_without_outbox(tmp_path, monkeypatch):
    push = _push_repository(tmp_path)
    first = push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/one",
        p256dh="p256dh-one",
        auth="auth-one",
    )
    push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/two",
        p256dh="p256dh-two",
        auth="auth-two",
    )
    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr("services.market.push_test.webpush", fake_webpush)

    result = send_test_push(
        push_repository=push,
        subscription=first,
        game_slug="delta-force",
        config=_config(),
    )

    assert result.ok is True
    assert result.status == "sent"
    assert result.response_status == 201
    assert len(calls) == 1
    assert calls[0]["subscription_info"]["endpoint"] == first.endpoint
    payload = json.loads(calls[0]["data"])
    assert payload["title"] == "魔丸娛樂測試通知"
    assert payload["url"] == "/games/delta-force/notifications"
    assert payload["data"] == {"kind": "push_test"}


def test_send_test_push_disables_expired_endpoint(tmp_path, monkeypatch):
    push = _push_repository(tmp_path)
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

    monkeypatch.setattr("services.market.push_test.webpush", expired_webpush)

    result = send_test_push(
        push_repository=push,
        subscription=subscription,
        game_slug="delta-force",
        config=_config(),
    )

    assert result.ok is False
    assert result.status == "expired"
    assert result.response_status == 410
    assert push.list_active_subscriptions("user-1") == ()


def test_send_test_push_sanitizes_transient_failure(tmp_path, monkeypatch):
    push = _push_repository(tmp_path)
    subscription = push.upsert_subscription(
        "user-1",
        endpoint="https://push.example.test/subscription/failure",
        p256dh="p256dh-failure",
        auth="auth-failure",
    )

    def failing_webpush(**_kwargs):
        raise RuntimeError("secret transport details")

    monkeypatch.setattr("services.market.push_test.webpush", failing_webpush)

    result = send_test_push(
        push_repository=push,
        subscription=subscription,
        game_slug="delta-force",
        config=_config(),
    )

    assert result.ok is False
    assert result.status == "failed"
    assert result.response_status is None
    assert len(push.list_active_subscriptions("user-1")) == 1
