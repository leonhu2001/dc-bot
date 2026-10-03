import json
import sqlite3
from datetime import datetime, timedelta, timezone

from web.app.services.operations_monitoring import (
    TAIPEI_TZ,
    build_cancellation_snapshot,
    build_smart_dispatch_snapshot,
)


def _setup_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                category TEXT,
                item TEXT,
                order_rule_key TEXT,
                amount INTEGER,
                customer_pay_amount INTEGER,
                status TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE smart_dispatch_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                dispatch_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT NOT NULL,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                allowed_role_ids_json TEXT NOT NULL DEFAULT '[]',
                required_game_role_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_staff_ids_json TEXT NOT NULL DEFAULT '[]',
                ranked_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                notified_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_sent_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_failed_ids_json TEXT NOT NULL DEFAULT '[]',
                stage INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                completion_reason TEXT,
                last_error TEXT
            );

            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                claimed_at TEXT NOT NULL
            );

            CREATE TABLE web_staff_members (
                discord_id TEXT PRIMARY KEY,
                roles_json TEXT,
                is_worker INTEGER NOT NULL DEFAULT 0,
                is_companion INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE order_cancellations (
                order_id INTEGER PRIMARY KEY,
                reason_code TEXT NOT NULL,
                reason_text TEXT,
                source TEXT NOT NULL,
                actor_discord_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE order_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                source TEXT NOT NULL,
                reason TEXT,
                actor_discord_id TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def test_smart_dispatch_snapshot_measures_fill_and_problem_plans(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    now = datetime.now(TAIPEI_TZ).replace(microsecond=0)
    plan1 = now - timedelta(minutes=10)
    claim1 = (
        plan1.astimezone(timezone.utc)
        + timedelta(minutes=2)
    ).replace(tzinfo=None)
    fill1 = (
        plan1.astimezone(timezone.utc)
        + timedelta(minutes=3)
    ).replace(tzinfo=None)
    plan2 = now - timedelta(minutes=5)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO web_orders (
                id, category, item, order_rule_key, amount,
                customer_pay_amount, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1, "三角洲", "娛樂陪", "", 500, 500, "active",
                    plan1.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                    plan1.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                ),
                (
                    2, "三角洲", "護航", "", 800, 800, "waiting_acceptance",
                    plan2.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                    plan2.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO smart_dispatch_notifications (
                order_id, dispatch_channel_id, dispatch_message_id,
                required_staff_count, ranked_candidate_ids_json,
                notified_candidate_ids_json, stage, created_at, updated_at,
                completed_at, completion_reason, last_error
            )
            VALUES (?, '10', '20', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1, 1, json.dumps(["A"]), json.dumps(["A"]),
                    2, plan1.isoformat(), now.isoformat(),
                    now.isoformat(), "order_status:accepted_pending_pay", None,
                ),
                (
                    2, 1, "[]", "[]",
                    2, plan2.isoformat(), now.isoformat(),
                    now.isoformat(), "full_expansion_sent", None,
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO order_acceptance_claims (
                order_id, staff_discord_id, claimed_at
            )
            VALUES (1, 'A', ?)
            """,
            (claim1.isoformat(),),
        )
        conn.execute(
            """
            INSERT INTO order_state_history (
                order_id, from_status, to_status, source, created_at
            )
            VALUES (
                1, 'waiting_acceptance', 'accepted_pending_pay',
                'test', ?
            )
            """,
            (fill1.isoformat(),),
        )
        conn.commit()

    snapshot = build_smart_dispatch_snapshot(
        days=30,
        db_file=db_path,
    )

    assert snapshot["total"] == 2
    assert snapshot["filled"] == 1
    assert snapshot["fill_rate"] == 50.0
    assert snapshot["avg_first_claim_seconds"] == 120
    assert snapshot["avg_fill_seconds"] == 180
    assert snapshot["no_candidate"] == 1
    assert snapshot["full_expansion"] == 1
    assert any(row["order_id"] == 2 for row in snapshot["problem_plans"])


def test_cancellation_snapshot_counts_rate_reasons_and_value(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    now = datetime.now(TAIPEI_TZ).replace(microsecond=0)
    created_utc = now.astimezone(timezone.utc).replace(tzinfo=None)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO web_orders (
                id, bot_order_no, category, item, amount,
                customer_pay_amount, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1, "MO-1", "三角洲", "護航", 500, 500,
                    "cancelled", created_utc.isoformat(), created_utc.isoformat(),
                ),
                (
                    2, "MO-2", "Steam", "娛樂陪", 300, 300,
                    "active", created_utc.isoformat(), created_utc.isoformat(),
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO order_cancellations (
                order_id, reason_code, reason_text, source,
                actor_discord_id, created_at
            )
            VALUES (1, 'no_staff', '晚班缺人', 'discord_cancel', 'staff-1', ?)
            """,
            (now.isoformat(),),
        )
        conn.commit()

    snapshot = build_cancellation_snapshot(
        days=30,
        db_file=db_path,
    )

    assert snapshot["orders_created"] == 2
    assert snapshot["cancelled_orders"] == 1
    assert snapshot["cancellation_rate"] == 50.0
    assert snapshot["lost_value"] == 500
    assert snapshot["unclassified"] == 0
    assert snapshot["reasons"] == [
        {
            "code": "no_staff",
            "label": "缺少可接人員",
            "count": 1,
        }
    ]
    assert snapshot["categories"][0]["category"] == "三角洲"
    assert snapshot["recent"][0]["reason_text"] == "晚班缺人"
