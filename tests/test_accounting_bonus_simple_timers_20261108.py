from __future__ import annotations

import sqlite3

import pytest

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
