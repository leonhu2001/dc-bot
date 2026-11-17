"""Paid clock must follow the order operation panel, never the checkout draft."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from services import simple_order_timer as timer
from services import order_operation_panel_runtime as operation


class FakeMessage:
    def __init__(self, channel, message_id, **kwargs):
        self.channel = channel
        self.id = message_id
        self.payload = kwargs
        self.edits = []

    async def delete(self):
        self.channel.messages.pop(self.id, None)
        self.channel.deleted.append(self.id)

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeChannel:
    def __init__(self, channel_id=123456789123456789):
        self.id = channel_id
        self.messages = {}
        self.deleted = []
        self.next_id = 1001
        self.sent = []

    async def fetch_message(self, message_id):
        return self.messages[int(message_id)]

    async def send(self, **kwargs):
        result = FakeMessage(self, self.next_id, **kwargs)
        self.messages[result.id] = result
        self.sent.append(result)
        self.next_id += 1
        return result


async def _no_prior_timer(_channel, _order_id):
    return None


def _setup(tmp_path, monkeypatch):
    database = tmp_path / "web_dashboard.db"
    channel = FakeChannel()
    with sqlite3.connect(database) as db:
        db.executescript(f"""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY, status TEXT, ticket_channel_id TEXT,
                item TEXT, quantity INTEGER, order_rule_key TEXT,
                rule_snapshot_json TEXT, amount INTEGER
            );
            CREATE TABLE order_assignments (
                order_id INTEGER, worker_discord_id TEXT, is_active INTEGER
            );
            INSERT INTO web_orders VALUES
                (42, 'accepted_pending_pay', '{channel.id}', 'STEAM娛樂陪',
                 2, 'steam_play', NULL, 900);
            INSERT INTO order_assignments VALUES (42, '12345', 1);
        """)
    monkeypatch.setattr(timer, "DATABASE", database)
    monkeypatch.setattr(timer, "_find_existing", _no_prior_timer)
    selections = {channel.id: {
        "status": "accepted_pending_pay", "operation_panel_message_id": None,
    }}
    monkeypatch.setattr(timer, "_ORDER_SELECTIONS", selections)
    monkeypatch.setattr(operation, "remember_order_data", lambda *a, **k: None)
    timer.ensure_tables()
    return database, channel, selections


def _status(db_path, status):
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE web_orders SET status=? WHERE id=42", (status,))


def test_payment_is_a_hard_prerequisite_for_new_timer(tmp_path, monkeypatch):
    db, channel, selections = _setup(tmp_path, monkeypatch)
    assert timer._eligible_orders() == []
    assert timer._operation_panel_id(channel.id) is None
    assert asyncio.run(timer.ensure_timer_panel_after_operation(channel, order_id=42)) is None
    assert not channel.sent

    # Even with a stale operation panel ID, WebOrder still gates payment.
    selections[channel.id] = {"status": "active", "operation_panel_message_id": 1000}
    assert asyncio.run(timer.ensure_timer_panel_after_operation(channel, order_id=42)) is None
    assert not channel.sent
    timer._register_order({"id": 42, "ticket_channel_id": str(channel.id)})
    with pytest.raises(ValueError, match="不是進行中"):
        timer.change_clock(channel.id, 12345, "start", now=100)
    assert not channel.sent

    # Canonical payment now active, but not until the operation panel exists.
    _status(db, "active")
    selections[channel.id]["operation_panel_message_id"] = None
    assert asyncio.run(timer.ensure_timer_panel_after_operation(channel, order_id=42)) is None
    assert not channel.sent

    selections[channel.id]["operation_panel_message_id"] = 1000
    assert [row["id"] for row in timer._eligible_orders()] == [42]
    assert asyncio.run(timer.ensure_timer_panel_after_operation(channel, order_id=42)) == 1001
    assert len(channel.sent) == 1


def test_reposition_moves_both_panels_but_keeps_elapsed_time(tmp_path, monkeypatch):
    db, channel, selections = _setup(tmp_path, monkeypatch)
    _status(db, "active")
    selections[channel.id] = {"status": "active", "operation_panel_message_id": 1000}
    channel.messages[1000] = FakeMessage(channel, 1000)

    async def exercise():
        first = await timer.ensure_timer_panel_after_operation(channel, order_id=42)
        assert first == 1001
        # No duplicate on the next worker pass or payment retry.
        assert await timer.ensure_timer_panel_after_operation(channel, order_id=42) == first
        assert len(channel.sent) == 1

        timer.change_clock(channel.id, 12345, "start", now=100)
        paused = timer.change_clock(channel.id, 12345, "pause", now=3700)
        assert timer.recorded_seconds(paused) == 3600

        await operation._reposition_panel(
            channel,
            expected_panel_message_id=1000,
            expected_status="active",
            order_selections=selections,
            operation_view_factory=lambda: object(),
        )
        assert selections[channel.id]["operation_panel_message_id"] == 1002
        assert timer._session(channel.id)["timer_message_id"] == "1003"
        assert 1001 in channel.deleted and 1000 in channel.deleted
        assert timer.recorded_seconds(timer._session(channel.id)) == 3600

        _status(db, "stored")
        selections[channel.id]["status"] = "stored"
        await operation._reposition_panel(
            channel, expected_panel_message_id=1002,
            expected_status="stored", order_selections=selections,
            operation_view_factory=lambda: object(),
        )
        assert selections[channel.id]["operation_panel_message_id"] == 1004
        assert timer._session(channel.id)["timer_message_id"] == "1005"
        assert timer.recorded_seconds(timer._session(channel.id)) == 3600

        _status(db, "active")
        selections[channel.id]["status"] = "active"
        await operation._reposition_panel(
            channel, expected_panel_message_id=1004,
            expected_status="active", order_selections=selections,
            operation_view_factory=lambda: object(),
        )
        assert selections[channel.id]["operation_panel_message_id"] == 1006
        assert timer._session(channel.id)["timer_message_id"] == "1007"
        assert timer._session(channel.id)["state"] == "paused"
        assert timer.recorded_seconds(timer._session(channel.id)) == 3600
        with pytest.raises(ValueError, match="最下方"):
            timer.change_clock(
                channel.id, 12345, "start",
                expected_message_id=1001, now=9000,
            )
        assert len(channel.sent) == 7
        assert set(channel.messages) == {1006, 1007}
        # A repeated interaction with a stale panel cannot create another pair.
        await operation._reposition_panel(
            channel, expected_panel_message_id=1004,
            expected_status="active", order_selections=selections,
            operation_view_factory=lambda: object(),
        )
        assert len(channel.sent) == 7
    asyncio.run(exercise())
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT amount FROM web_orders WHERE id=42").fetchone()[0] == 900


def test_old_prepaid_timer_message_is_removed_without_zeroing_its_db_state(
    tmp_path, monkeypatch
):
    db, channel, selections = _setup(tmp_path, monkeypatch)
    timer._register_order({"id": 42, "ticket_channel_id": str(channel.id)})
    old = FakeMessage(channel, 999)
    channel.messages[999] = old
    timer._set_message_id(42, 999)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE simple_order_timers SET state='paused', elapsed_seconds=3600 WHERE order_id=42"
        )
    async def fake_channel(_bot, _channel_id):
        return channel

    monkeypatch.setattr(timer, "_channel", fake_channel)
    monkeypatch.setattr(timer.discord, "TextChannel", FakeChannel)
    asyncio.run(timer.hide_early_unpaid_timer_panels(object()))
    session = timer._session(channel.id)
    assert session["timer_message_id"] == "0"
    assert session["state"] == "paused"
    assert timer.recorded_seconds(session) == 3600
    assert 999 in channel.deleted
    assert not channel.messages


def test_explicit_payment_and_manager_restore_hooks_remain_source_owned():
    root = Path(__file__).resolve().parents[1]
    payment = (root / "services/order_payment_runtime.py").read_text(encoding="utf-8")
    bot = (root / "bot.py").read_text(encoding="utf-8")
    assert 'await ensure_timer_panel_after_operation(' in payment
    assert 'interaction.channel, order_id=int(web_order_id)' in payment
    assert 'install_simple_order_timer(bot, SELF_SERVICE_ORDER_SELECTIONS)' in bot
    assert 'operation_view_factory=StaffOrderOperationView' in bot


def test_clock_buttons_and_stale_operation_confirm_never_repost(monkeypatch):
    from types import SimpleNamespace

    class FakeMember:
        pass

    channel = FakeChannel()
    channel.messages[1000] = FakeMessage(channel, 1000)
    selections = {
        channel.id: {"status": "active", "operation_panel_message_id": 1000}
    }
    monkeypatch.setattr(operation.discord, "Member", FakeMember)
    monkeypatch.setattr(operation.discord, "TextChannel", FakeChannel)
    user = FakeMember()

    async def run(custom_id, message_id):
        message = FakeMessage(channel, message_id)
        message.flags = SimpleNamespace(ephemeral=False)
        interaction = SimpleNamespace(
            type=operation.discord.InteractionType.component,
            user=user, channel=channel, message=message,
            data={"custom_id": custom_id},
        )
        await operation.handle_order_operation_panel_interaction(
            interaction,
            order_selections=selections,
            is_staff=lambda _member: True,
            operation_view_factory=lambda: object(),
        )

    asyncio.run(run("simple_hourly_timer:start", 1001))
    asyncio.run(run("simple_hourly_timer:pause", 1001))
    asyncio.run(run("staff_order_operation_confirm", 999))
    assert channel.sent == []
    assert set(channel.messages) == {1000}
