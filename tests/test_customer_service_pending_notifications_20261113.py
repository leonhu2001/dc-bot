from __future__ import annotations

import sqlite3

from services.customer_service_pending_notifications import (
    _mark,
    _migrate_column,
    _payment_embed,
    _rows,
    _transfer_embed,
)


def _connector(path):
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    return connect


def test_cs_payment_notification_is_idempotent_and_resolves(tmp_path):
    path = tmp_path / "cs-payment-notification.sqlite3"
    conn = _connector(path)()
    try:
        conn.execute("CREATE TABLE payment_reviews (id INTEGER PRIMARY KEY, status TEXT, "
                     "review_no TEXT, amount INTEGER, payment_method TEXT)")
        conn.execute("INSERT INTO payment_reviews VALUES (11, 'pending_review', 'PAY-11', 1200, 'bank_transfer')")
        _migrate_column(conn, "payment_reviews", "cs_notice_message_id")
        _migrate_column(conn, "payment_reviews", "cs_notice_resolved_at")
        conn.commit()
    finally:
        conn.close()

    connect = _connector(path)
    pending, resolved = _rows(connect, "payment_reviews", "pending_review")
    assert len(pending) == 1
    assert not resolved
    embed = _payment_embed(pending[0])
    assert "付款審核" in embed.title
    assert any(field.name == "金額" and field.value == "1,200T" for field in embed.fields)

    _mark(connect, "payment_reviews", 11, message_id=12345)
    pending, resolved = _rows(connect, "payment_reviews", "pending_review")
    assert not pending
    assert not resolved

    conn = connect()
    try:
        conn.execute("UPDATE payment_reviews SET status='applied' WHERE id=11")
        conn.commit()
    finally:
        conn.close()
    pending, resolved = _rows(connect, "payment_reviews", "pending_review")
    assert not pending
    assert len(resolved) == 1
    _mark(connect, "payment_reviews", 11)
    assert _rows(connect, "payment_reviews", "pending_review") == ([], [])


def test_cs_transfer_notice_contains_review_context():
    row = {
        "id": 9, "status": "pending",
        "amount": 850, "from_employee_display_name": "小明",
        "to_employee_display_name": "小美",
        "created_by_display_name": "小明", "reason": "調整",
    }
    embed = _transfer_embed(row)
    assert embed.title.startswith("💸 內部轉帳")
    assert any(field.name == "金額" and field.value == "850T" for field in embed.fields)
    assert any(field.name == "轉入" and field.value == "小美" for field in embed.fields)
