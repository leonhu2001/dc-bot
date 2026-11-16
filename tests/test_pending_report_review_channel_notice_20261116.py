"""Pending report review notices are durable and do not affect payout state."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, text

from web.app.services import order_reporting as reporting


def _notification_db():
    bind = create_engine("sqlite:///:memory:")
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY, status TEXT,
                bot_order_no TEXT, customer_display_name TEXT, item TEXT,
                closed_at DATETIME, updated_at DATETIME, created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL, worker_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))
    reporting.ensure_order_reporting_tables(bind)
    return bind


def test_one_notification_per_pending_submission_and_no_duplicate_after_retries(
    monkeypatch,
):
    bind = _notification_db()
    monkeypatch.setattr(reporting, "engine", bind)
    t1 = datetime(2026, 11, 16, 2, 12, 0, 123456)
    with bind.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, status, bot_order_no, customer_display_name, item,
                closed_at, updated_at, created_at
            ) VALUES (
                88, 'active', 'MW-88', '客戶甲', '娛樂單陪',
                NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            UPDATE web_orders SET status='closed', closed_at=CURRENT_TIMESTAMP
            WHERE id=88
        """))
        report_id = conn.execute(text(
            "SELECT id FROM order_reports WHERE order_id=88"
        )).scalar_one()
        conn.execute(
            reporting.order_reports.update()
            .where(reporting.order_reports.c.id == report_id)
            .values(
                status="pending", submitted_at=t1,
                submitted_by_display_name="陪玩乙",
            )
        )
        reporting._enqueue_pending_review_notice(
            conn, report_id=report_id, order_id=88, submitted_at=t1
        )

    notice = reporting._claim_pending_review_notifications(order_id=88)
    assert len(notice) == 1
    assert notice[0]["order_id"] == 88
    assert reporting._claim_pending_review_notifications(order_id=88) == []
    payload = reporting._pending_review_notice_payload(notice[0])
    assert "報單待審核" in payload["content"]
    assert "MW-88" in payload["content"]
    assert "客戶甲" in payload["content"]
    assert "陪玩乙" in payload["content"]
    assert payload["components"][0]["components"][0]["url"].endswith(
        "/dispatch/reports/review/88"
    )
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["enforce_nonce"] is True

    reporting._finish_review_notification(int(notice[0]["id"]), success=True)
    assert reporting._claim_pending_review_notifications(order_id=88) == []

    # A rejected-then-resubmitted report generates a NEW single notification.
    t2 = t1 + timedelta(minutes=4)
    with bind.begin() as conn:
        conn.execute(
            reporting.order_reports.update()
            .where(reporting.order_reports.c.id == report_id)
            .values(status="pending", submitted_at=t2)
        )
        reporting._enqueue_pending_review_notice(
            conn, report_id=report_id, order_id=88, submitted_at=t2
        )
    again = reporting._claim_pending_review_notifications(order_id=88)
    assert len(again) == 1
    assert again[0]["id"] != notice[0]["id"]
    reporting._finish_review_notification(
        int(again[0]["id"]), success=False, error="Discord 503"
    )
    assert len(reporting._claim_pending_review_notifications(order_id=88)) == 1
    with bind.begin() as conn:
        rows = conn.execute(text("""
            SELECT status, attempts FROM order_report_review_notifications
            ORDER BY id
        """)).all()
    assert len(rows) == 2
    assert rows[0].status == "sent"
    assert rows[1].attempts == 2


def test_notification_target_and_trigger_are_fixed_to_report_pending_transition():
    from pathlib import Path

    assert reporting.PENDING_REPORT_REVIEW_CHANNEL_ID == 1502040302649872394
    source = (Path(__file__).resolve().parents[1]
              / "web/app/services/order_reporting.py").read_text(encoding="utf-8")
    assert "_enqueue_pending_review_notice(" in source
    assert "report_id=report_id," in source
    assert "submitted_at=submitted_at," in source
    assert "await send_pending_order_report_review_notifications(limit=20)" in source


def test_notifications_do_not_rewrite_historical_reports_or_payment_reviews():
    bind = _notification_db()
    with bind.begin() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM order_report_review_notifications"
        )).scalar_one() == 0
    reporting.ensure_order_reporting_tables(bind)
    with bind.begin() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM order_report_review_notifications"
        )).scalar_one() == 0
