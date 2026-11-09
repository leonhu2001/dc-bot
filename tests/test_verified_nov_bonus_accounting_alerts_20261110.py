from __future__ import annotations

import json
import sqlite3

import pytest

from web.app.services.accounting_reconciliation_policy import (
    _is_verified_nov_bonus_repair,
    _policy_consistency_for_order,
    _should_suppress_amount_mismatch,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE web_orders(
            id INTEGER PRIMARY KEY, bot_order_no TEXT,
            status TEXT, amount INTEGER, payout_base_amount INTEGER,
            price_snapshot_json TEXT, order_rule_key TEXT,
            customer_pay_amount INTEGER
        );
        CREATE TABLE order_reports(
            id INTEGER PRIMARY KEY, order_id INTEGER,
            status TEXT, is_legacy INTEGER
        );
        CREATE TABLE worker_payouts(
            id INTEGER PRIMARY KEY, order_id INTEGER,
            worker_discord_id TEXT, gross_share INTEGER,
            final_payout INTEGER, note TEXT
        );
        CREATE TABLE customer_service_payouts(
            id INTEGER PRIMARY KEY, order_id INTEGER, payout_amount INTEGER
        );
        CREATE TABLE admin_audit_logs(
            id INTEGER PRIMARY KEY, action TEXT, target_type TEXT,
            target_id TEXT, before_json TEXT, after_json TEXT
        );
        CREATE TABLE worker_payout_overrides(
            order_id INTEGER, worker_discord_id TEXT
        );
    """)
    for order_id, number, base, gross, old, worker, cs_old, cs in [
        (298, "MO20261102001", 1440, 720, 576, 590, 72, 68),
        (300, "MO20261103002", 900, 450, 360, 369, 45, 43),
    ]:
        conn.execute(
            "INSERT INTO web_orders VALUES(?,?,?,?,?,?,?,?)",
            (order_id, number, "closed", base, base, "{}", "lol_ng", base),
        )
        conn.execute(
            "INSERT INTO order_reports VALUES(?,?,'approved',1)",
            (order_id, order_id),
        )
        conn.execute(
            "INSERT INTO worker_payouts VALUES(?,?,?,?,?,?)",
            (order_id, order_id, "1029311167212036116", gross, worker,
             "分潤：基礎80%＋前月業績達5000T 2%｜前月業績 13801T"),
        )
        conn.execute(
            "INSERT INTO worker_payouts VALUES(?,?,?,?,?,?)",
            (order_id + 1000, order_id, "other_worker", gross, round(gross * 0.80), ""),
        )
        conn.execute(
            "INSERT INTO customer_service_payouts VALUES(?,?,?)",
            (order_id, order_id, cs),
        )
        conn.execute(
            "INSERT INTO admin_audit_logs VALUES(?,?,?,?,?,?)",
            (order_id, "restore_november_bonus_verified_20261110",
             "order", str(order_id),
             json.dumps({"worker": old, "cs": cs_old}),
             json.dumps({"worker": worker, "cs": cs})),
        )
    yield conn
    conn.close()


@pytest.mark.parametrize("order_id", [298, 300])
def test_audited_2pct_bonus_with_old_legacy_flag_does_not_realert(db, order_id):
    assert _is_verified_nov_bonus_repair(db, order_id)
    state = _policy_consistency_for_order(db, order_id)
    assert state == {
        "new_policy": True,
        "provisional": False,
        "worker_consistent": True,
        "cs_consistent": True,
    }
    for code in (
        "worker_payout_amount_mismatch",
        "customer_service_payout_amount_mismatch",
    ):
        assert _should_suppress_amount_mismatch({"code": code}, state)


@pytest.mark.parametrize("change", [
    "DELETE FROM admin_audit_logs WHERE target_id='298'",
    "UPDATE admin_audit_logs SET after_json='{}' WHERE target_id='298'",
    "UPDATE worker_payouts SET final_payout=589 WHERE order_id=298 AND worker_discord_id='1029311167212036116'",
    "UPDATE worker_payouts SET final_payout=575 WHERE order_id=298 AND worker_discord_id='other_worker'",
    "UPDATE worker_payouts SET note='' WHERE order_id=298 AND worker_discord_id='1029311167212036116'",
    "UPDATE worker_payouts SET gross_share=719 WHERE order_id=298 AND worker_discord_id='1029311167212036116'",
    "UPDATE customer_service_payouts SET payout_amount=69 WHERE order_id=298",
    "UPDATE web_orders SET bot_order_no='MO-wrong' WHERE id=298",
    "INSERT INTO worker_payout_overrides VALUES(298,'1029311167212036116')",
])
def test_changed_ledger_or_missing_proof_keeps_both_anomalies_visible(db, change):
    db.execute(change)
    assert not _is_verified_nov_bonus_repair(db, 298)
    state = _policy_consistency_for_order(db, 298)
    assert not state["new_policy"]
    assert not _should_suppress_amount_mismatch(
        {"code": "worker_payout_amount_mismatch"}, state
    )
    assert not _should_suppress_amount_mismatch(
        {"code": "customer_service_payout_amount_mismatch"}, state
    )


def test_pending_report_does_not_hide_amount_mismatch(db):
    db.execute("UPDATE order_reports SET status='pending' WHERE order_id=298")
    state = _policy_consistency_for_order(db, 298)
    assert state["provisional"]
    assert not state["worker_consistent"]
    assert not state["cs_consistent"]
    # Existing behavior for provisional orders remains intact.


def test_legacy_orders_without_targeted_repair_are_not_suppressed(db):
    db.execute("UPDATE web_orders SET id=999 WHERE id=298")
    db.execute("UPDATE worker_payouts SET order_id=999 WHERE order_id=298")
    db.execute("UPDATE customer_service_payouts SET order_id=999 WHERE order_id=298")
    db.execute("UPDATE order_reports SET order_id=999 WHERE order_id=298")
    state = _policy_consistency_for_order(db, 999)
    assert state["new_policy"] is False
