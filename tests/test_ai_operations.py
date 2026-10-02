import sqlite3
from datetime import datetime, timedelta, timezone

from web.app.services.ai_operations import (
    _compact_report,
    _extract_response_text,
    _usage,
    build_recent_order_signals,
    fallback_operations_summary,
)


def _utc_text(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds"
    )


def _create_signal_db(path):
    now = datetime.now(timezone.utc)

    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                category TEXT,
                item TEXT,
                status TEXT,
                created_at TEXT
            );

            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                required_staff_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                claimed_at TEXT NOT NULL
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO web_orders (
                id, category, item, status, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "basic",
                    "商品 A",
                    "closed",
                    _utc_text(now - timedelta(days=2)),
                ),
                (
                    2,
                    "basic",
                    "商品 A",
                    "cancelled",
                    _utc_text(now - timedelta(days=1)),
                ),
                (
                    3,
                    "basic",
                    "商品 A",
                    "closed",
                    _utc_text(now - timedelta(days=18)),
                ),
                (
                    4,
                    "basic",
                    "商品 B",
                    "closed",
                    _utc_text(now - timedelta(days=3)),
                ),
            ],
        )

        meta_created = now - timedelta(days=1)
        conn.execute(
            """
            INSERT INTO order_acceptance_meta (
                order_id, required_staff_count, created_at
            )
            VALUES (?, ?, ?)
            """,
            (1, 1, _utc_text(meta_created)),
        )
        conn.execute(
            """
            INSERT INTO order_acceptance_claims (
                order_id, staff_discord_id, claimed_at
            )
            VALUES (?, ?, ?)
            """,
            (
                1,
                "staff-secret-id",
                _utc_text(meta_created + timedelta(minutes=4)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_recent_order_signals_are_aggregate_and_no_staff_ids(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _create_signal_db(db_path)

    snapshot = build_recent_order_signals(db_file=db_path)

    assert snapshot["daily"]
    assert snapshot["service_change_14d"]
    assert snapshot["acceptance_by_hour_30d"]

    service_a = next(
        item
        for item in snapshot["service_change_14d"]
        if item["label"] == "商品 A"
    )
    assert service_a["current_14d_orders"] == 2
    assert service_a["current_14d_cancelled"] == 1
    assert service_a["current_14d_cancellation_rate"] == 50.0
    assert service_a["previous_14d_orders"] == 1

    serialized = str(snapshot)
    assert "staff-secret-id" not in serialized


def test_compact_report_drops_worker_identity_rows():
    report = {
        "period": "month",
        "period_label": "本月",
        "previous_label": "上月同期",
        "comparison_history_exists": True,
        "revenue": 1000,
        "payroll": 700,
        "retained": 300,
        "retained_rate": 30.0,
        "payroll_rate": 70.0,
        "order_count": 2,
        "avg_order": 500,
        "customer_count": 2,
        "repeat_customers": 0,
        "repeat_rate": 0.0,
        "discount_total": 0,
        "created_orders": 3,
        "cancelled_orders": 1,
        "cancellation_rate": 33.3,
        "worker_rows": [
            {
                "worker_discord_id": "secret-worker",
                "name": "Secret Worker",
                "amount": 700,
            }
        ],
        "service_rows": [
            {
                "label": "商品 A",
                "orders": 2,
                "revenue": 1000,
                "payroll": 700,
                "retained": 300,
                "retained_rate": 30.0,
            }
        ],
        "payment_rows": [],
        "daily_labels": ["2026-10-01"],
        "daily_values": [1000],
        "comparison": {},
    }

    compact = _compact_report(report)

    assert compact["revenue"] == 1000
    assert compact["services"][0]["label"] == "商品 A"
    assert "worker_rows" not in compact
    assert "secret-worker" not in str(compact)
    assert "Secret Worker" not in str(compact)


def test_operations_response_and_usage_parsers():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "營運分析完成",
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
    }

    assert _extract_response_text(payload) == "營運分析完成"
    assert _usage(payload) == (100, 20, 120)


def test_fallback_summary_uses_only_aggregate_metrics():
    snapshot = {
        "financial_orders": {
            "period_label": "本月",
            "revenue": 1000,
            "order_count": 2,
            "retained": 300,
            "retained_rate": 30.0,
            "created_orders": 3,
            "cancelled_orders": 1,
            "cancellation_rate": 33.3,
        },
        "anomalies": {
            "issue_count": 2,
            "critical_count": 1,
        },
        "customer_service": {
            "within_5_rate": 80.0,
        },
    }

    text = fallback_operations_summary(snapshot)

    assert "本月營收 1,000" in text
    assert "取消率 33.3%" in text
    assert "Critical 1" in text
