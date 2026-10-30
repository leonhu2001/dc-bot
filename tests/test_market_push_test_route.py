import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.market.push_dispatcher import WebPushConfig
from web.app.routers import market_push


class _Request:
    def __init__(self, user_id: str, endpoint: str):
        self.session = {"user": {"id": user_id}}
        self._endpoint = endpoint

    async def json(self):
        return {"endpoint": self._endpoint}


def _config() -> WebPushConfig:
    return WebPushConfig(
        public_key="test-public",
        private_key="test-private",
        subject="mailto:test@example.com",
    )


def test_push_test_only_targets_current_users_subscription(monkeypatch):
    owned = SimpleNamespace(
        id=1,
        discord_user_id="user-1",
        endpoint="https://push.example.test/owned",
        p256dh="p256dh-owned",
        auth="auth-owned",
    )
    other = SimpleNamespace(
        id=2,
        discord_user_id="user-2",
        endpoint="https://push.example.test/other",
        p256dh="p256dh-other",
        auth="auth-other",
    )

    class _PushRepository:
        def list_active_subscriptions(self, user_id):
            return (owned,) if user_id == "user-1" else (other,)

    calls = []

    def fake_send_test_push(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="sent", ok=True)

    monkeypatch.setattr(
        market_push,
        "_game_or_404",
        lambda _slug: SimpleNamespace(slug="delta-force", key="delta_force"),
    )
    monkeypatch.setattr(market_push, "get_web_push_config", _config)
    monkeypatch.setattr(market_push, "get_market_push_repository", lambda: _PushRepository())
    monkeypatch.setattr(market_push, "send_test_push", fake_send_test_push)

    response = asyncio.run(
        market_push.market_push_test(
            _Request("user-1", owned.endpoint),
            "delta-force",
        )
    )

    assert response == {"ok": True, "status": "sent"}
    assert len(calls) == 1
    assert calls[0]["subscription"] is owned

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            market_push.market_push_test(
                _Request("user-1", other.endpoint),
                "delta-force",
            )
        )
    assert exc.value.status_code == 404
    assert len(calls) == 1
