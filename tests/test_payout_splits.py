from __future__ import annotations

import sqlite3

import pytest

from web.app.services import payout_splits


def _create_schema(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                status TEXT,
                category TEXT,
                item TEXT,
                quantity INTEGER,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT
            );
            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                final_payout INTEGER NOT NULL DEFAULT 0,
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE worker_payout_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                manual_final_payout INTEGER NOT NULL DEFAULT 0,
                reason TEXT,
                created_by_discord_id TEXT,
                created_by_display_name TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_order(path, *, source_status="unpaid", target_status="unpaid"):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO web_orders (
                id, bot_order_no, status, category, item, quantity,
                created_at, updated_at, closed_at
            ) VALUES (1, 'MW-001', 'closed', '英雄聯盟', '娛樂陪', 4,
                      '2026-10-11 01:00:00', '2026-10-11 02:00:00', '2026-10-11 02:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO worker_payouts (
                order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status, created_at, updated_at
            ) VALUES (1, 'worker-a', '小玄', 400, ?, '2026-10-11 02:00:00', '2026-10-11 02:00:00')
            """,
            (source_status,),
        )
        conn.execute(
            """
            INSERT INTO worker_payouts (
                order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status, created_at, updated_at
            ) VALUES (1, 'worker-b', '麻糬', 400, ?, '2026-10-11 02:00:00', '2026-10-11 02:00:00')
            """,
            (target_status,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def split_db(tmp_path, monkeypatch):
    path = tmp_path / "payout_splits.db"
    _create_schema(path)
    monkeypatch.setattr(payout_splits, "db_path", lambda: str(path))
    payout_splits.ensure_payout_split_tables()
    return path


def test_approved_split_moves_pay_without_changing_total(split_db):
    _seed_order(split_db)

    split_id = payout_splits.create_payout_split(
        order_id=1,
        from_worker_discord_id="worker-a",
        from_worker_display_name="小玄",
        to_worker_discord_id="worker-b",
        amount=200,
        hours=1,
        reason="實際陪玩 3H / 1H",
    )

    result = payout_splits.decide_payout_split(
        split_id=split_id,
        actor_discord_id="worker-b",
        actor_display_name="麻糬",
        approve=True,
    )

    assert result["status"] == "approved"

    conn = sqlite3.connect(split_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT worker_discord_id, final_payout FROM worker_payouts ORDER BY worker_discord_id"
        ).fetchall()
        amounts = {row["worker_discord_id"]: row["final_payout"] for row in rows}
        assert amounts == {"worker-a": 200, "worker-b": 600}
        assert sum(amounts.values()) == 800

        overrides = conn.execute(
            "SELECT worker_discord_id, manual_final_payout FROM worker_payout_overrides"
        ).fetchall()
        override_amounts = {
            row["worker_discord_id"]: row["manual_final_payout"] for row in overrides
        }
        assert override_amounts == {"worker-a": 200, "worker-b": 600}
    finally:
        conn.close()


def test_pending_requests_reserve_available_amount(split_db):
    _seed_order(split_db)

    payout_splits.create_payout_split(
        order_id=1,
        from_worker_discord_id="worker-a",
        from_worker_display_name="小玄",
        to_worker_discord_id="worker-b",
        amount=300,
        reason="第一筆",
    )

    orders = payout_splits.list_eligible_orders("worker-a")
    assert orders[0]["source_amount"] == 400
    assert orders[0]["reserved_amount"] == 300
    assert orders[0]["available_amount"] == 100

    with pytest.raises(ValueError, match="可分帳金額只剩 100T"):
        payout_splits.create_payout_split(
            order_id=1,
            from_worker_discord_id="worker-a",
            from_worker_display_name="小玄",
            to_worker_discord_id="worker-b",
            amount=101,
            reason="第二筆超額",
        )


def test_paid_payout_cannot_be_split(split_db):
    _seed_order(split_db, source_status="paid")

    assert payout_splits.list_eligible_orders("worker-a") == []

    with pytest.raises(ValueError, match="薪資已經發放"):
        payout_splits.create_payout_split(
            order_id=1,
            from_worker_discord_id="worker-a",
            from_worker_display_name="小玄",
            to_worker_discord_id="worker-b",
            amount=100,
            reason="不應允許",
        )


def test_only_recipient_or_manager_can_approve(split_db):
    _seed_order(split_db)
    split_id = payout_splits.create_payout_split(
        order_id=1,
        from_worker_discord_id="worker-a",
        from_worker_display_name="小玄",
        to_worker_discord_id="worker-b",
        amount=100,
        reason="雙方確認",
    )

    with pytest.raises(ValueError, match="只有收款人或總管"):
        payout_splits.decide_payout_split(
            split_id=split_id,
            actor_discord_id="worker-c",
            actor_display_name="其他人",
            approve=True,
        )

    payout_splits.decide_payout_split(
        split_id=split_id,
        actor_discord_id="manager-1",
        actor_display_name="總管",
        approve=True,
        is_manager=True,
    )
