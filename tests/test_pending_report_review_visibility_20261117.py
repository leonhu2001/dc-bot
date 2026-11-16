"""Regression coverage: pending review must be visible even with missing backlog."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from web.app.services import order_reporting as reporting


def _db(monkeypatch):
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY, status TEXT NOT NULL,
                bot_order_no TEXT, customer_display_name TEXT,
                category TEXT, item TEXT, closed_at DATETIME,
                updated_at DATETIME, created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER,
                worker_discord_id TEXT, worker_display_name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))
    reporting.ensure_order_reporting_tables(bind)
    monkeypatch.setattr(reporting, "engine", bind)
    monkeypatch.setattr(reporting, "ensure_order_reporting_tables", lambda *a, **k: None)
    return bind


def _insert_closed(bind, first, last):
    with bind.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, status, bot_order_no, customer_display_name,
                category, item, closed_at, updated_at, created_at
            ) VALUES (
                :id, 'closed', :order_no, 'customer', 'delta', 'hourly',
                '2026-11-16 10:00:00', '2026-11-16 10:00:00',
                '2026-11-16 09:00:00'
            )
        """), [
            {"id": i, "order_no": f"MO-{i}"}
            for i in range(first, last + 1)
        ])


def _make_pending(bind, ids):
    with bind.begin() as conn:
        for i in ids:
            conn.execute(text("""
                UPDATE order_reports
                SET status='pending', submitted_at=:now
                WHERE order_id=:id
            """), {"id": i, "now": f"2026-11-16 12:{i % 60:02d}:00"})


def test_pending_reports_show_before_missing_backlog(monkeypatch):
    bind = _db(monkeypatch)
    _insert_closed(bind, 1, 303)
    _make_pending(bind, (301, 302, 303))

    records = reporting.list_reports_for_review(status_filter="actionable", limit=250)
    assert len(records) == 250
    assert [r["id"] for r in records[:3]] == [303, 302, 301]
    assert all(r["report_status"] == "pending" for r in records[:3])
    assert reporting.count_pending_review_reports() == 3

    only_pending = reporting.list_reports_for_review(status_filter="pending", limit=250)
    assert {r["id"] for r in only_pending} == {301, 302, 303}


def test_review_list_supports_pagination_past_500_pending(monkeypatch):
    bind = _db(monkeypatch)
    _insert_closed(bind, 1, 520)
    _make_pending(bind, range(1, 521))

    first = reporting.list_reports_for_review(status_filter="pending", limit=251, offset=0)
    middle = reporting.list_reports_for_review(status_filter="pending", limit=251, offset=250)
    last = reporting.list_reports_for_review(status_filter="pending", limit=251, offset=500)
    assert len(first) == 251
    assert len(middle) == 251
    assert len(last) == 20
    assert len({r["id"] for r in first[:250] + middle[:250] + last}) == 520


def test_pending_anomalies_visible_but_nonpending_open_orders_stay_hidden(monkeypatch):
    bind = _db(monkeypatch)
    _insert_closed(bind, 1, 3)
    _make_pending(bind, (1, 2))
    with bind.begin() as conn:
        conn.execute(text("UPDATE web_orders SET status='active' WHERE id IN (1,3)"))

    rows = reporting.list_reports_for_review(status_filter="actionable", limit=250)
    assert [(r["id"], r["order_status"], r["report_status"]) for r in rows] == [
        (2, "closed", "pending"), (1, "active", "pending")
    ]
    assert {r["id"] for r in reporting.list_reports_for_review(status_filter="pending")} == {1,2}
    assert reporting.count_pending_review_reports() == 2
    assert reporting.list_reports_for_review(status_filter="missing") == []
