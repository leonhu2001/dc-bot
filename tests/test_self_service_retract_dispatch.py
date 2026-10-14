from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import discord

from services import self_service_runtime
from services.acceptance import runtime as acceptance_runtime
from services import loyalty_benefits, vip_monthly_benefits
from shared import db as shared_db
from shared import order_acceptance, web_order_sync


class _FakeResult:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _ClaimConnection:
    def execute(self, _statement, _params=None):
        return _FakeResult(rows=[{"staff_discord_id": "9001"}])


class _ClaimEngine:
    @contextmanager
    def begin(self):
        yield _ClaimConnection()


class _FakeMessage:
    def __init__(self, message_id: int):
        self.id = int(message_id)
        self.deleted = False
        self.edits = []

    async def delete(self):
        self.deleted = True

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = int(channel_id)
        self.mention = f"<#{channel_id}>"
        self.messages = {}

    async def fetch_message(self, message_id: int):
        message_id = int(message_id)
        if message_id not in self.messages:
            raise RuntimeError("message missing")
        return self.messages[message_id]


class _FakeGuild:
    def __init__(self, *channels):
        self._channels = {int(channel.id): channel for channel in channels}
        self.member = SimpleNamespace(id=9001)

    def get_channel(self, channel_id):
        return self._channels.get(int(channel_id))

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    def get_member(self, member_id):
        return self.member if int(member_id) == 9001 else None

    async def fetch_member(self, member_id):
        return self.get_member(member_id)


class _FakeDeleteSession:
    def __init__(self):
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if sql.startswith("SELECT id FROM web_orders"):
            return _FakeResult(first=(321,))
        if "sqlite_master" in sql:
            return _FakeResult(first=(1,))
        return _FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")

    def close(self):
        pass


def test_retract_dispatch_keeps_draft_and_cleans_prepay_state(monkeypatch):
    ticket = _FakeTextChannel(6001)
    dispatch = _FakeTextChannel(6002)
    dispatch_message = _FakeMessage(7001)
    payment_message = _FakeMessage(7002)
    dispatch.messages[7001] = dispatch_message
    ticket.messages[7002] = payment_message
    guild = _FakeGuild(ticket, dispatch)
    interaction = SimpleNamespace(
        guild=guild,
        channel=ticket,
        user=SimpleNamespace(id=8001, mention="<@8001>"),
    )

    draft = {
        "customer_id": 5001,
        "category": "delta",
        "item": "娛樂陪",
        "quantity": 3,
        "dispatch_message_id": 7001,
        "dispatch_channel_id": 6002,
        "web_order_id": 321,
        "status": "waiting_acceptance",
        "payment_message_id": 7002,
        "payment_method": "待付款",
    }
    claims = {
        7001: {
            "source_channel_id": 6001,
            "booster": {9001},
            "companion": set(),
        }
    }
    remembered = []
    deleted_claim_rows = []
    cancelled = []
    revoked = []
    deleted_web = []

    monkeypatch.setattr(self_service_runtime.discord, "TextChannel", _FakeTextChannel)
    monkeypatch.setattr(self_service_runtime, "SELF_SERVICE_ORDER_SELECTIONS", {6001: draft}, raising=False)
    monkeypatch.setattr(self_service_runtime, "ORDER_CLAIMS", claims, raising=False)
    monkeypatch.setattr(self_service_runtime, "DISPATCH_CHANNEL_ID", 6002, raising=False)
    monkeypatch.setattr(self_service_runtime, "remember_order_data", lambda *args: remembered.append(args))
    monkeypatch.setattr(self_service_runtime, "save_bot_data", lambda: None)
    monkeypatch.setattr(
        self_service_runtime,
        "delete_claim_row_from_db",
        lambda **kwargs: deleted_claim_rows.append(kwargs),
    )
    monkeypatch.setattr(self_service_runtime, "get_taipei_now_iso", lambda: "2026-10-15T02:45:00+08:00")

    async def _noop_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(self_service_runtime, "send_order_log", _noop_log, raising=False)
    monkeypatch.setattr(
        order_acceptance,
        "get_acceptance_state",
        lambda _order_id: SimpleNamespace(status="waiting_acceptance"),
    )
    monkeypatch.setattr(
        order_acceptance,
        "cancel_acceptance_order",
        lambda order_id, **kwargs: cancelled.append((order_id, kwargs)),
    )
    monkeypatch.setattr(shared_db, "engine", _ClaimEngine())

    async def _revoke(_guild, channel_id, member):
        revoked.append((channel_id, member.id))
        return True

    monkeypatch.setattr(acceptance_runtime, "revoke_order_ticket_access", _revoke)
    monkeypatch.setattr(
        web_order_sync,
        "delete_web_order_by_ticket_channel",
        lambda **kwargs: deleted_web.append(kwargs) or True,
    )

    result = asyncio.run(
        self_service_runtime.retract_waiting_acceptance_order_from_self_service(
            interaction,
            channel_id=6001,
        )
    )

    assert "已撤回派單" in result
    assert dispatch_message.deleted is True
    assert payment_message.deleted is True
    assert cancelled and cancelled[0][0] == 321
    assert revoked == [(6001, 9001)]
    assert deleted_web == [{"ticket_channel_id": 6001, "dispatch_message_id": 7001}]
    assert 7001 not in claims
    assert deleted_claim_rows
    assert draft["item"] == "娛樂陪"
    assert draft["quantity"] == 3
    assert draft["category"] == "delta"
    assert draft["closed"] is False
    assert draft["dispatch_retracted_by"] == 8001
    assert "dispatch_message_id" not in draft
    assert "dispatch_channel_id" not in draft
    assert "web_order_id" not in draft
    assert "status" not in draft
    assert "payment_message_id" not in draft
    assert "payment_method" not in draft
    assert remembered


def test_deleted_web_order_releases_benefits_and_purges_prepay_tables(monkeypatch):
    session = _FakeDeleteSession()
    released_coupon = []
    released_vip = []

    monkeypatch.setattr(shared_db, "SessionLocal", lambda: session)
    monkeypatch.setattr(loyalty_benefits, "release_coupon_for_order", lambda order_id: released_coupon.append(order_id) or 1)
    monkeypatch.setattr(vip_monthly_benefits, "release_cash_benefits_for_channel", lambda channel_id: released_vip.append(str(channel_id)) or 1)

    assert web_order_sync.delete_web_order_by_ticket_channel(
        ticket_channel_id=6001,
        dispatch_message_id=7001,
    ) is True

    sql_text = "\n".join(sql for sql, _params in session.statements)
    assert released_coupon == [321]
    assert released_vip == ["6001"]
    assert "DELETE FROM order_acceptance_claims" in sql_text
    assert "DELETE FROM order_acceptance_meta" in sql_text
    assert "DELETE FROM smart_dispatch_notifications" in sql_text
    assert "DELETE FROM web_orders" in sql_text
    assert session.committed is True


def test_dispatched_view_is_persistent_and_has_retract_button():
    view = self_service_runtime.SelfServiceDispatchedView()
    assert view.timeout is None
    retract_buttons = [
        child for child in view.children
        if getattr(child, "custom_id", None) == "self_service_retract_dispatch_button"
    ]
    assert len(retract_buttons) == 1
    assert retract_buttons[0].label == "撤回派單"
