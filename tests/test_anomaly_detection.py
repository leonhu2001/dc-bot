import sqlite3
from datetime import datetime, timedelta, timezone

from web.app.services import anomaly_detection


TAIPEI_TZ = timezone(timedelta(hours=8))


def _create_web_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                status TEXT,
                ticket_channel_id TEXT,
                dispatch_channel_id TEXT,
                dispatch_message_id TEXT,
                customer_discord_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                is_active INTEGER
            );

            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                status TEXT
            );

            CREATE TABLE payment_reviews (
                id INTEGER PRIMARY KEY,
                review_no TEXT,
                source_type TEXT,
                source_id TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                apply_error TEXT
            );

            CREATE TABLE sync_events (
                id INTEGER PRIMARY KEY,
                event_type TEXT,
                status TEXT,
                order_id INTEGER,
                error_message TEXT,
                retry_count INTEGER,
                created_at TEXT,
                processed_at TEXT
            );
            """
        )
        conn.commit()


def _create_bot_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE topup_orders (
                id INTEGER PRIMARY KEY,
                topup_no TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.commit()


def _empty_accounting(*args, **kwargs):
    return {
        "issue_count": 0,
        "critical_count": 0,
        "warning_count": 0,
        "issues": [],
    }


def test_naive_sqlalchemy_timestamp_is_treated_as_utc():
    now = datetime(2026, 10, 2, 4, 0, tzinfo=TAIPEI_TZ)

    age = anomaly_detection._age_minutes(
        "2026-10-01 20:00:00",
        now=now,
    )

    assert age == 0


def test_anomaly_snapshot_detects_cross_system_failures(tmp_path, monkeypatch):
    web_path = tmp_path / "web_dashboard.db"
    bot_path = tmp_path / "bot.db"
    _create_web_db(web_path)
    _create_bot_db(bot_path)

    now = datetime(2026, 10, 2, 4, 0, tzinfo=TAIPEI_TZ)

    with sqlite3.connect(web_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (
                id, bot_order_no, status, ticket_channel_id,
                dispatch_channel_id, dispatch_message_id,
                customer_discord_id, created_at, updated_at
            )
            VALUES (
                1, 'MO-1', 'waiting_acceptance', '100',
                '200', NULL, '300',
                '2026-10-01 17:00:00', '2026-10-01 18:00:00'
            );

            INSERT INTO order_acceptance_meta(order_id, status)
            VALUES (1, 'active');

            INSERT INTO web_orders (
                id, bot_order_no, status, ticket_channel_id,
                dispatch_channel_id, dispatch_message_id,
                customer_discord_id, created_at, updated_at
            )
            VALUES (
                2, 'MO-2', 'accepted_pending_pay', '101',
                '201', '301', '301',
                '2026-10-01 18:00:00', '2026-10-01 19:00:00'
            );

            INSERT INTO payment_reviews (
                id, review_no, source_type, source_id, status,
                created_at, updated_at, apply_error
            )
            VALUES (
                7, 'PAY-7', 'order', '2', 'apply_error',
                '2026-10-02T03:00:00+08:00',
                '2026-10-02T03:30:00+08:00',
                'runtime failure'
            );

            INSERT INTO sync_events (
                id, event_type, status, order_id, error_message,
                retry_count, created_at, processed_at
            )
            VALUES (
                9, 'order_updated', 'pending', 2, NULL,
                0, '2026-10-01 18:30:00', NULL
            );
            """
        )
        conn.commit()

    with sqlite3.connect(bot_path) as conn:
        conn.execute(
            """
            INSERT INTO topup_orders (
                id, topup_no, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                5,
                "TOPUP-5",
                "crediting",
                "2026-10-02T03:00:00+08:00",
                "2026-10-02T03:30:00+08:00",
            ),
        )
        conn.commit()

    monkeypatch.setattr(
        anomaly_detection,
        "build_accounting_reconciliation_snapshot",
        _empty_accounting,
    )

    snapshot = anomaly_detection.build_anomaly_snapshot(
        tmp_path,
        now=now,
    )

    codes = {item["code"] for item in snapshot["issues"]}

    assert snapshot["status"] == "critical"
    assert snapshot["critical_count"] >= 5
    assert "order_state_drift" in codes
    assert "waiting_order_dispatch_reference_missing" in codes
    assert "accepted_order_assignment_missing" in codes
    assert "payment_apply_error" in codes
    assert "sync_event_pending_stalled" in codes
    assert "topup_crediting_stalled" in codes

    payment = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "payment_apply_error"
    )
    assert payment["action_url"] == "/admin/payment-reviews"


def test_anomaly_snapshot_merges_accounting_issues(tmp_path, monkeypatch):
    _create_web_db(tmp_path / "web_dashboard.db")
    _create_bot_db(tmp_path / "bot.db")

    monkeypatch.setattr(
        anomaly_detection,
        "build_accounting_reconciliation_snapshot",
        lambda *args, **kwargs: {
            "issue_count": 1,
            "critical_count": 1,
            "warning_count": 0,
            "issues": [
                {
                    "category": "order_payment",
                    "code": "wallet_order_tx_missing",
                    "severity": "critical",
                    "reference": "MO-99",
                    "title": "錢包付款訂單缺少扣款流水",
                    "detail": "test",
                    "order_id": 99,
                }
            ],
        },
    )

    snapshot = anomaly_detection.build_anomaly_snapshot(
        tmp_path,
        now=datetime(2026, 10, 2, 4, 0, tzinfo=TAIPEI_TZ),
    )

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "wallet_order_tx_missing"
    )

    assert issue["category"] == "accounting"
    assert issue["source"] == "accounting"
    assert issue["action_url"] == "/admin/order-workspace/99"
    assert snapshot["accounting_issue_count"] == 1


def test_empty_sources_return_ok(tmp_path, monkeypatch):
    _create_web_db(tmp_path / "web_dashboard.db")
    _create_bot_db(tmp_path / "bot.db")

    monkeypatch.setattr(
        anomaly_detection,
        "build_accounting_reconciliation_snapshot",
        _empty_accounting,
    )

    snapshot = anomaly_detection.build_anomaly_snapshot(
        tmp_path,
        now=datetime(2026, 10, 2, 4, 0, tzinfo=TAIPEI_TZ),
    )

    assert snapshot["status"] == "ok"
    assert snapshot["issue_count"] == 0
    assert snapshot["issues"] == []
