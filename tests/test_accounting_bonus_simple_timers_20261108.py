from __future__ import annotations

import sqlite3

import pytest

from services import simple_order_timer as timer
from web.app.services.accounting_reconciliation_policy import _rate_from_persisted_note


@pytest.mark.parametrize("bonus_note", [
    "前月業績達5000T 2%",
    "前月已結算薪資達5000T 2%",
])
def test_both_previous_month_bonus_note_formats_are_recognized(bonus_note):
    assert _rate_from_persisted_note("分潤：基礎80%＋" + bonus_note) == pytest.approx(0.82)
    assert _rate_from_persisted_note(
        "分潤：基礎80%＋掛名3%＋直播2%＋" + bonus_note + "＋綁店3%"
    ) == pytest.approx(0.90)


@pytest.mark.parametrize("category,pricing,expected", [
    ("steam", "hourly", True),
    ("lol", "hourly", True),
    ("apex", "hourly", True),
    ("valorant", "hourly", True),
    ("lol", "game", False),
    ("delta_desktop_basic", "hourly", False),
    ("vip_timer", "hourly", False),
])
def test_hourly_clock_scope_uses_actual_rule_category_and_rate(
    category, pricing, expected, monkeypatch
):
    from types import SimpleNamespace

    monkeypatch.setattr(
        timer, "get_rule", lambda _: SimpleNamespace(category=category, pricing_type=pricing)
    )
    assert timer.eligible_hourly_rule("example") is expected


def test_simple_clock_persists_hours_and_rejects_customer_and_non_worker(
    tmp_path, monkeypatch
):
    path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(timer, "DATABASE", path)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE web_orders(
                id INTEGER PRIMARY KEY, status TEXT, ticket_channel_id TEXT,
                item TEXT, quantity INTEGER, order_rule_key TEXT,
                rule_snapshot_json TEXT
            );
            CREATE TABLE order_assignments (
                order_id INTEGER, worker_discord_id TEXT, is_active INTEGER
            );
            INSERT INTO web_orders VALUES
                (12,'active','10001','Steam',2,'steam_play',NULL);
            INSERT INTO order_assignments VALUES (12,'20001',1);
            INSERT INTO order_assignments VALUES (12,'20002',0);
        """)
    timer.ensure_tables()
    assert timer._register_order({"id": 12, "ticket_channel_id": "10001"})
    with pytest.raises(PermissionError, match="接單陪玩"):
        timer.change_clock(10001, 30001, "start", now=10)
    with pytest.raises(PermissionError):
        timer.change_clock(10001, 20002, "start", now=10)

    started = timer.change_clock(10001, 20001, "start", now=10)
    assert started["state"] == "running"
    assert timer.recorded_seconds(started, now=3610) == 3600
    with pytest.raises(ValueError, match="重複"):
        timer.change_clock(10001, 20001, "start", now=3611)

    paused = timer.change_clock(10001, 20001, "pause", now=3610)
    assert paused["state"] == "paused"
    assert timer.recorded_seconds(paused, now=7210) == 3600
    timer.change_clock(10001, 20001, "start", now=7210)
    paused_again = timer.change_clock(10001, 20001, "pause", now=9010)
    assert timer.recorded_seconds(paused_again, now=9999) == 5400
    assert timer._duration(5400) == "01:30:00"

    with sqlite3.connect(path) as db:
        db.execute("UPDATE web_orders SET status='closed' WHERE id=12")
    ended = timer._finish_non_active()
    assert ended == [(12, "10001")]
    assert timer._session(10001)["state"] == "finished"
    with pytest.raises(ValueError, match="不是進行中"):
        timer.change_clock(10001, 20001, "start", now=10000)


def test_frozen_non_hourly_snapshot_blocks_accidental_timer(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        timer, "get_rule", lambda _: SimpleNamespace(category="steam", pricing_type="hourly")
    )
    assert not timer.eligible_hourly_rule("steam_play", '{"pricing_type":"game"}')


def test_approved_bonus_payout_is_not_flagged_as_base_only_accounting_error():
    from web.app.services.accounting_reconciliation_policy import (
        _policy_consistency_for_order, _should_suppress_amount_mismatch,
    )
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE web_orders(
            id INTEGER PRIMARY KEY, status TEXT, amount INTEGER,
            payout_base_amount INTEGER, price_snapshot_json TEXT,
            order_rule_key TEXT, customer_pay_amount INTEGER
        );
        INSERT INTO web_orders VALUES
            (1, 'closed', 1000, 1000, '{}', 'lol_ng', 1000);
        CREATE TABLE order_reports(
            id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT,
            is_legacy INTEGER
        );
        INSERT INTO order_reports VALUES (1, 1, 'approved', 0);
        CREATE TABLE worker_payouts(
            id INTEGER PRIMARY KEY, order_id INTEGER,
            worker_discord_id TEXT, gross_share INTEGER,
            final_payout INTEGER, note TEXT
        );
        INSERT INTO worker_payouts VALUES
            (1,1,'staff-a',1000,820,
             '分潤：基礎80%＋前月業績達5000T 2%｜前月業績 6000T');
        CREATE TABLE customer_service_payouts(
            id INTEGER PRIMARY KEY, order_id INTEGER, payout_amount INTEGER
        );
        INSERT INTO customer_service_payouts VALUES (1,1,45);
    """)
    state = _policy_consistency_for_order(db, 1)
    assert state["worker_consistent"]
    assert state["cs_consistent"]
    for code in (
        "worker_payout_amount_mismatch",
        "customer_service_payout_amount_mismatch",
    ):
        assert _should_suppress_amount_mismatch({"code": code}, state)
    db.close()
