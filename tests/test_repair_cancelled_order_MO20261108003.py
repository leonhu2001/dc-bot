from __future__ import annotations

import json
import sqlite3

import pytest

from scripts.repair_cancelled_order_MO20261108003 import (
    CUSTOMER_ID,
    ORDER_NO,
    TICKET_ID,
    execute,
)


def setup_dbs(root):
    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.executescript("""
        CREATE TABLE web_orders (
          id INTEGER PRIMARY KEY, bot_order_no TEXT, status TEXT,
          customer_discord_id TEXT, ticket_channel_id TEXT,
          payment_method TEXT, amount INTEGER
        );
        CREATE TABLE payment_reviews (
          id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT,
          customer_discord_id TEXT, ticket_channel_id TEXT, review_no TEXT
        );
        CREATE TABLE order_assignments (id INTEGER PRIMARY KEY, order_id INTEGER);
        CREATE TABLE sync_events (id INTEGER PRIMARY KEY, order_id INTEGER);
        INSERT INTO web_orders VALUES
          (3, 'MO20261108003', 'cancelled', '519545372194656316',
          '1568952422544711726', '轉帳', 3750),
          (6, 'MO20261108006', 'active', '519545372194656316',
          '1568963971048935614', '轉帳', 3000);
        INSERT INTO payment_reviews VALUES
          (2, 'order', '3', '519545372194656316',
          '1568952422544711726', 'PAY-20261108-0002'),
          (3, 'order', '6', '519545372194656316',
          '1568963971048935614', 'PAY-20261108-0003');
        INSERT INTO order_assignments VALUES (3, 3), (6, 6);
        INSERT INTO sync_events VALUES (3, 3), (6, 6);
        """)
    with sqlite3.connect(root / "bot.db") as conn:
        conn.executescript("""
        CREATE TABLE customers (
          customer_id INTEGER PRIMARY KEY, total_spent INTEGER,
          points INTEGER, completed_orders INTEGER,
          level TEXT, data_json TEXT, updated_at TEXT
        );
        CREATE TABLE orders (channel_id INTEGER PRIMARY KEY, data_json TEXT);
        CREATE TABLE wallet_transactions (
          id INTEGER PRIMARY KEY, order_no TEXT, order_channel_id TEXT
        );
        CREATE TABLE claims (
          dispatch_message_id INTEGER PRIMARY KEY, source_channel_id TEXT
        );
        """)
        conn.execute(
            "INSERT INTO customers VALUES (?,6750,67,2,'金級魔丸',?,NULL)",
            (int(CUSTOMER_ID), json.dumps({
                "total_spent": 6750, "points": 67, "order_count": 2,
                "point_adjustment": 0, "vip_level_index": 2,
                "vip_progress_reset_active": False,
            })),
        )
        conn.execute(
            "INSERT INTO orders VALUES (?, ?)",
            (int(TICKET_ID), json.dumps({
                "customer_id": int(CUSTOMER_ID),
                "order_no": ORDER_NO, "web_order_id": 3,
                "amount": 3750, "reward_counted": True,
                "reward_amount": 3750,
            })),
        )
        conn.execute(
            "INSERT INTO orders VALUES (?, ?)",
            (1568963971048935614, json.dumps({
                "customer_id": int(CUSTOMER_ID), "order_no": "MO20261108006",
                "amount": 3000,
            })),
        )
        conn.execute(
            "INSERT INTO wallet_transactions VALUES (3,'MO20261108006','1568963971048935614')"
        )


def test_target_repair_removes_only_cancelled_order_and_reverses_vip_once(tmp_path, monkeypatch):
    setup_dbs(tmp_path)
    dry = execute(root=tmp_path)
    assert dry["state"] == "ready"
    assert dry["vip_before"] == 6750
    assert dry["vip_after"] == 3000
    assert dry["points_after"] == 30
    assert dry["reviews"] == ["PAY-20261108-0002"]

    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    result = execute(root=tmp_path, apply=True)
    assert result["state"] == "applied"
    assert result["payment_reviews_deleted"] == 1
    assert result["web_children_deleted"] == 2

    with sqlite3.connect(tmp_path / "web_dashboard.db") as conn:
        assert conn.execute("SELECT bot_order_no FROM web_orders").fetchall() == [
            ("MO20261108006",)
        ]
        assert conn.execute("SELECT review_no FROM payment_reviews").fetchall() == [
            ("PAY-20261108-0003",)
        ]
        assert conn.execute("SELECT order_id FROM order_assignments").fetchall() == [(6,)]
        assert conn.execute("SELECT order_id FROM sync_events").fetchall() == [(6,)]
        assert conn.execute("SELECT COUNT(*) FROM one_time_data_repairs").fetchone()[0] == 1

    with sqlite3.connect(tmp_path / "bot.db") as conn:
        member = conn.execute(
            "SELECT total_spent, points, completed_orders, level, data_json FROM customers"
        ).fetchone()
        assert member[:4] == (3000, 30, 1, "銀級魔丸")
        extra = json.loads(member[4])
        assert extra["total_spent"] == 3000
        assert extra["points"] == 30
        assert extra["vip_level_index"] == 1
        assert conn.execute("SELECT channel_id FROM orders").fetchall() == [
            (1568963971048935614,)
        ]
        assert conn.execute("SELECT order_no FROM wallet_transactions").fetchall() == [
            ("MO20261108006",)
        ]

    assert (tmp_path / "_archive").exists()
    assert len(list((tmp_path / "_archive").glob("*/bot.db"))) == 1
    assert execute(root=tmp_path, apply=True)["state"] == "already_applied"


def test_without_explicit_maintenance_never_writes(tmp_path):
    setup_dbs(tmp_path)
    with pytest.raises(RuntimeError, match="停機維護"):
        execute(root=tmp_path, apply=True)
    assert execute(root=tmp_path)["vip_before"] == 6750


@pytest.mark.parametrize("mutation", [
    "UPDATE web_orders SET status='active' WHERE id=3",
    "UPDATE web_orders SET customer_discord_id='another' WHERE id=3",
    "UPDATE web_orders SET amount=3450 WHERE id=3",
    "UPDATE web_orders SET ticket_channel_id='other' WHERE id=3",
])
def test_wrong_order_identity_is_rejected(tmp_path, monkeypatch, mutation):
    setup_dbs(tmp_path)
    with sqlite3.connect(tmp_path / "web_dashboard.db") as conn:
        conn.execute(mutation)
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    with pytest.raises(RuntimeError, match="安全檢查"):
        execute(root=tmp_path, apply=True)
    with sqlite3.connect(tmp_path / "web_dashboard.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_orders").fetchone()[0] == 2


def test_other_member_spend_changes_require_reinspection(tmp_path, monkeypatch):
    setup_dbs(tmp_path)
    with sqlite3.connect(tmp_path / "bot.db") as conn:
        conn.execute(
            "UPDATE customers SET total_spent=6900 WHERE customer_id=?",
            (int(CUSTOMER_ID),),
        )
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    with pytest.raises(RuntimeError, match="6900"):
        execute(root=tmp_path, apply=True)


def test_wallet_ledger_never_silently_deleted(tmp_path, monkeypatch):
    setup_dbs(tmp_path)
    with sqlite3.connect(tmp_path / "bot.db") as conn:
        conn.execute(
            "INSERT INTO wallet_transactions VALUES (4,?,?)",
            (ORDER_NO, TICKET_ID),
        )
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    with pytest.raises(RuntimeError, match="實際錢包流水"):
        execute(root=tmp_path, apply=True)


def test_already_reversed_vip_does_not_deduct_again(tmp_path, monkeypatch):
    setup_dbs(tmp_path)
    with sqlite3.connect(tmp_path / "bot.db") as conn:
        conn.execute(
            "UPDATE customers SET total_spent=3000, points=30, "
            "completed_orders=1, level='銀級魔丸' WHERE customer_id=?",
            (int(CUSTOMER_ID),),
        )
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    result = execute(root=tmp_path, apply=True)
    assert result["vip_before"] == 3000
    assert result["completed_before"] == result["completed_after"] == 1
