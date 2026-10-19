from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from services import order_credential_revocation as revocation
from services import order_credential_runtime as runtime
from services import order_credentials


def test_runtime_delegates_credential_revocation_to_extracted_service() -> None:
    runtime_source = Path("services/order_credential_runtime.py").read_text(encoding="utf-8")
    extracted_source = Path("services/order_credential_revocation.py").read_text(encoding="utf-8")

    assert "_revoke_order_credential_messages(" in runtime_source
    assert "list_active_deliveries" not in runtime_source
    assert "list_active_deliveries" in extracted_source
    assert "import bot" not in extracted_source
    assert "from bot import" not in extracted_source
    assert callable(runtime.revoke_order_credential_messages)


def test_revocation_marks_missing_delivery_metadata_without_resolving_user(monkeypatch) -> None:
    revoked: list[tuple[int, str, str]] = []
    resolver_calls: list[tuple[object, int]] = []

    monkeypatch.setattr(
        order_credentials,
        "list_active_deliveries",
        lambda _order_id: [
            {
                "id": 7,
                "recipient_discord_id": None,
                "dm_message_id": None,
                "recipient_type": "worker",
                "recipient_display_name": "測試打手",
            }
        ],
    )
    monkeypatch.setattr(order_credentials, "get_order_context", lambda _order_id: {})
    monkeypatch.setattr(
        order_credentials,
        "mark_delivery_revoked",
        lambda delivery_id, *, status, reason: revoked.append(
            (delivery_id, status, reason)
        ),
    )

    async def resolve_user(guild, user_id):
        resolver_calls.append((guild, user_id))
        return None

    result = asyncio.run(
        revocation.revoke_order_credential_messages(
            123,
            reason="test",
            notify_customer=False,
            to_int=lambda value, default=None: default if value is None else int(value),
            resolve_user=resolve_user,
            fallback_guild=None,
            taipei_now_iso=lambda: "2026-10-19T00:00:00+08:00",
        )
    )

    assert result == {"total": 1, "deleted": 1, "failed": 0}
    assert revoked == [(7, "metadata_missing", "test")]
    assert resolver_calls == []


def test_runtime_revocation_wrapper_keeps_public_signature() -> None:
    signature = inspect.signature(runtime.revoke_order_credential_messages)
    assert list(signature.parameters) == [
        "order_id",
        "reason",
        "ticket_channel",
        "notify_customer",
    ]
