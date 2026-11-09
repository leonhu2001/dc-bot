from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from views import staff_profile_tip_ticket as tip_view
from web.app.routers import admin_payout_summary as admin


def test_profile_tip_receipt_has_paid_amount_and_close_button(monkeypatch):
    monkeypatch.setattr(tip_view, "profile_tip_ticket_ids", lambda _: (123, 456))
    channel = SimpleNamespace(send=AsyncMock())
    asyncio.run(tip_view.send_profile_tip_paid_panel(channel, {
        "payment_status": "paid",
        "customer_discord_id": "123",
        "worker_discord_id": "456",
        "amount": 200,
        "payment_method": "我的錢包",
    }))
    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert isinstance(kwargs["view"], tip_view.WorkerTipProfileCloseView)
    assert kwargs["view"].is_persistent()
    assert "200T 已付款" in channel.send.await_args.args[0]
    assert "已列入薪資明細" in channel.send.await_args.args[0]


def test_profile_tip_close_requires_double_confirmation(monkeypatch):
    class FakeChannel:
        topic = "profile_tip_customer_id=123;profile_tip_staff_id=456"

    monkeypatch.setattr(discord, "TextChannel", FakeChannel)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = SimpleNamespace(
        channel=FakeChannel(), user=SimpleNamespace(id=123), response=response,
    )
    asyncio.run(tip_view.request_profile_tip_close(interaction))
    response.send_message.assert_awaited_once()
    kwargs = response.send_message.await_args.kwargs
    assert kwargs["ephemeral"] is True
    assert "確定要關閉" in response.send_message.await_args.args[0]
    from views.review import ConfirmCloseTicketView
    assert isinstance(kwargs["view"], ConfirmCloseTicketView)


def test_profile_tip_creation_grants_chosen_worker_explicit_access(monkeypatch):
    class FakeMember:
        def __init__(self, user_id):
            self.id = user_id
            self.mention = f"<@{user_id}>"

    monkeypatch.setattr(discord, "Member", FakeMember)
    from views import staff_profiles
    monkeypatch.setattr(staff_profiles, "get_staff_profile", lambda _: {"display_name": "護航"})
    customer = FakeMember(123)
    staff = FakeMember(456)
    support = SimpleNamespace(id=99, mention="<@&99>")
    guild = SimpleNamespace(
        get_member=lambda mid: staff if mid == 456 else None,
        get_role=lambda rid: support if rid == 99 else None,
    )
    channel_creator = AsyncMock()
    asyncio.run(tip_view.create_staff_profile_tip_ticket(
        interaction=SimpleNamespace(guild=guild, user=customer),
        staff_id="456", create_private_channel=channel_creator,
        customer_role_id=99, customer_category_id=77,
    ))
    channel_creator.assert_awaited_once()
    args = channel_creator.await_args.kwargs
    assert args["allowed_roles"] == [support, staff]
    assert args["topic"] == "profile_tip_customer_id=123;profile_tip_staff_id=456"


def _db(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE web_orders(
                id INTEGER PRIMARY KEY, bot_order_no TEXT, status TEXT,
                category TEXT, item TEXT, customer_display_name TEXT,
                customer_discord_id TEXT, closed_at TEXT, updated_at TEXT, created_at TEXT
            );
            CREATE TABLE worker_payouts(
                id INTEGER PRIMARY KEY, order_id INTEGER, worker_discord_id TEXT,
                worker_display_name TEXT, final_payout INTEGER, payout_status TEXT,
                paid_at TEXT
            );
            CREATE TABLE order_reports(order_id INTEGER, status TEXT);
            CREATE TABLE customer_service_payouts(
                id INTEGER PRIMARY KEY, order_id INTEGER,
                customer_service_discord_id TEXT, customer_service_display_name TEXT,
                payout_amount INTEGER, payout_status TEXT, paid_at TEXT
            );
            CREATE TABLE web_staff_members(
                discord_id TEXT, is_worker INTEGER, is_companion INTEGER,
                is_customer_service INTEGER
            );
            CREATE TABLE worker_tips(
                id INTEGER PRIMARY KEY, order_id INTEGER, ticket_channel_id TEXT,
                customer_discord_id TEXT, customer_display_name TEXT,
                worker_discord_id TEXT, worker_display_name TEXT, amount INTEGER,
                payment_status TEXT, payout_status TEXT, payout_paid_at TEXT,
                created_at TEXT, updated_at TEXT, paid_at TEXT
            );
            INSERT INTO worker_tips VALUES
                (78,NULL,'100','999','老闆阿堯','123','測試陪玩',400,
                 'paid','unpaid',NULL,'2026-11-09 01:00:00',
                 '2026-11-09 01:02:00','2026-11-09 01:02:00'),
                (79,NULL,'101','999','另一個老闆','123','測試陪玩',900,
                 'pending_review','unpaid',NULL,'2026-11-09 02:00:00',
                 '2026-11-09 02:02:00',NULL);
        """)


def test_admin_salary_totals_and_mark_paid_include_standalone_tips(tmp_path, monkeypatch):
    path = tmp_path / "dashboard.db"
    _db(path)
    monkeypatch.setattr(admin, "db_path", lambda: str(path))
    monkeypatch.setattr(admin, "summary_db_path", lambda: str(path))
    rows, totals = admin.fetch_rows("2026-11", "worker", "", status="unpaid")
    assert totals["unpaid_total"] == 400
    assert totals["unpaid_count"] == 1
    assert rows[0]["discord_id"] == "123"
    assert any(item["order_no"] == "TIP-78" for item in rows[0]["items"])
    assert "2026-11" in {row["value"] for row in admin.get_summary_month_options()}
    admin.update_summary_person_payout_status("2026-11", "worker", "123", "paid")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT payout_status FROM worker_tips WHERE id=78"
        ).fetchone()[0] == "paid"
        assert db.execute(
            "SELECT payout_status FROM worker_tips WHERE id=79"
        ).fetchone()[0] == "unpaid"
    rows, totals = admin.fetch_rows("2026-11", "worker", "", status="paid")
    assert totals["paid_total"] == 400
