from __future__ import annotations

import sqlite3

from web.app.services import payout_notifications


def _snapshot(*, worker_unpaid=0, tip_unpaid=0, cs_unpaid=0):
    return {
        "month": "2026-10",
        "worker_payouts": {
            "unpaid": {"count": worker_unpaid, "total": worker_unpaid * 100},
        },
        "worker_tips": {
            "unpaid": {"count": tip_unpaid, "total": tip_unpaid * 50},
        },
        "customer_service_payouts": {
            "unpaid": {"count": cs_unpaid, "total": cs_unpaid * 30},
        },
    }


def test_paid_notification_only_fires_for_newly_paid_salary():
    before = _snapshot(worker_unpaid=1, tip_unpaid=1)
    paid_after = {
        **_snapshot(),
        "target_status": "paid",
        "person_role": "worker",
    }

    assert payout_notifications.should_send_payout_paid_notification(
        before=before,
        after=paid_after,
    ) is True

    assert payout_notifications.should_send_payout_paid_notification(
        before=_snapshot(),
        after=paid_after,
    ) is False

    assert payout_notifications.should_send_payout_paid_notification(
        before=before,
        after={**paid_after, "target_status": "unpaid"},
    ) is False


def test_salary_notification_includes_worker_income_and_chicken_leg(tmp_path, monkeypatch):
    db_file = tmp_path / "salary.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                status TEXT,
                category TEXT,
                item TEXT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT
            );

            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                final_payout INTEGER,
                payout_status TEXT
            );

            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                amount INTEGER,
                payment_status TEXT,
                payout_status TEXT
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                payout_amount INTEGER,
                payout_status TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders (
                id, bot_order_no, status, category, item,
                created_at, updated_at, closed_at
            ) VALUES (1, 'MW-1001', 'closed', 'delta', '技術陪',
                      '2026-10-03 10:00:00', '2026-10-03 11:00:00',
                      '2026-10-03 11:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO worker_payouts (
                id, order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status
            ) VALUES (1, 1, '123', '測試陪玩', 500, 'paid')
            """
        )
        conn.execute(
            """
            INSERT INTO worker_tips (
                id, order_id, worker_discord_id, worker_display_name,
                amount, payment_status, payout_status
            ) VALUES (1, 1, '123', '測試陪玩', 100, 'paid', 'paid')
            """
        )
        conn.commit()
    finally:
        conn.close()

    sent = []

    def fake_send_direct_message(discord_user_id, *, content=None, embeds=None):
        sent.append({
            "discord_user_id": str(discord_user_id),
            "content": content,
            "embeds": embeds,
        })
        return {"id": str(len(sent))}

    monkeypatch.setattr(
        payout_notifications,
        "send_direct_message",
        fake_send_direct_message,
    )

    result = payout_notifications.send_payout_paid_notification(
        db_file=db_file,
        person_id="123",
        before=_snapshot(worker_unpaid=1, tip_unpaid=1),
        after={
            **_snapshot(),
            "target_status": "paid",
            "person_role": "worker",
        },
    )

    assert result["sent"] is True
    assert result["total"] == 600
    assert result["worker_total"] == 500
    assert result["tip_total"] == 100
    assert len(sent) == 2

    embed_text = str(sent[0]["embeds"])
    detail_text = str(sent[1]["content"])
    assert "600T" in embed_text
    assert "🍗 雞腿" in embed_text
    assert "MW-1001" in detail_text
    assert "🍗 雞腿" in detail_text
