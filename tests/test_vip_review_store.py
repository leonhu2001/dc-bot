import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from services.vip_review_store import (
    build_vip_retention_status,
    build_vip_review_snapshot,
    queue_vip_review_action,
    set_vip_protection,
)

TAIPEI = timezone(timedelta(hours=8))


def _dt(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=TAIPEI)


def test_retention_policy_varies_by_vip_tier():
    now = _dt(2026, 10, 10)

    silver = build_vip_retention_status(
        {"total_spent": 2000, "last_order_at": _dt(2026, 9, 9).isoformat()},
        now=now,
    )
    diamond = build_vip_retention_status(
        {"total_spent": 25000, "last_order_at": _dt(2026, 7, 20).isoformat()},
        now=now,
    )

    assert silver["current_level"] == "銀級魔丸"
    assert silver["retention_days"] == 30
    assert silver["is_due"] is True

    assert diamond["current_level"] == "鑽石魔丸"
    assert diamond["retention_days"] == 90
    assert diamond["is_due"] is False


def test_manual_adjustment_time_becomes_new_retention_anchor():
    now = _dt(2026, 10, 10)
    status = build_vip_retention_status(
        {
            "total_spent": 50000,
            "vip_level_index": 3,
            "vip_progress_base_total_spent": 50000,
            "vip_progress_reset_active": True,
            "last_order_at": _dt(2026, 1, 1).isoformat(),
            "last_level_manual_fixed_at": _dt(2026, 10, 1).isoformat(),
            "last_level_manual_fixed_reason": "人工降階",
        },
        now=now,
    )

    assert status["current_level"] == "白金魔丸"
    assert status["retention_days"] == 60
    assert status["is_due"] is False
    assert status["days_remaining"] > 0


def test_protection_extends_review_deadline_without_changing_last_order():
    now = _dt(2026, 10, 10)
    data = {
        "total_spent": 6000,
        "last_order_at": _dt(2026, 8, 1).isoformat(),
    }

    overdue = build_vip_retention_status(data, now=now)
    protected = build_vip_retention_status(
        data,
        protection_until=_dt(2026, 10, 20).isoformat(),
        now=now,
    )

    assert overdue["is_due"] is True
    assert protected["is_due"] is False
    assert protected["last_order_at"] == data["last_order_at"]
    assert protected["protection_until"].startswith("2026-10-20")


def test_snapshot_reads_customer_json_and_pending_state(tmp_path):
    db = tmp_path / "bot.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE customers (
                customer_id TEXT PRIMARY KEY,
                total_spent INTEGER,
                points INTEGER,
                completed_orders INTEGER,
                last_order_at TEXT,
                level TEXT,
                platinum_channel_id TEXT,
                data_json TEXT,
                updated_at TEXT
            )
            """
        )
        data = {
            "total_spent": 25000,
            "last_order_at": _dt(2026, 6, 1).isoformat(),
        }
        conn.execute(
            """
            INSERT INTO customers (
                customer_id,total_spent,last_order_at,level,data_json
            ) VALUES (?,?,?,?,?)
            """,
            ("100", 25000, data["last_order_at"], "鑽石魔丸", json.dumps(data)),
        )
        conn.commit()

    snapshot = build_vip_review_snapshot(
        db_file=db,
        view="pending",
        now=_dt(2026, 10, 10),
    )

    assert snapshot["stats"]["vip_count"] == 1
    assert snapshot["stats"]["pending_count"] == 1
    assert snapshot["rows"][0]["customer_id"] == "100"
    assert snapshot["rows"][0]["suggested_level"] == "白金魔丸"


def test_customer_service_extension_is_limited_to_30_days(tmp_path):
    db = tmp_path / "bot.db"

    with pytest.raises(ValueError, match="1～30"):
        queue_vip_review_action(
            customer_id="100",
            action="extend",
            reason="特殊保級",
            operator_discord_id="200",
            operator_display_name="客服",
            operator_is_manager=False,
            extend_days=31,
            db_file=db,
        )

    action_id = queue_vip_review_action(
        customer_id="100",
        action="extend",
        reason="特殊保級",
        operator_discord_id="200",
        operator_display_name="客服",
        operator_is_manager=False,
        extend_days=30,
        db_file=db,
    )
    assert action_id == 1


def test_protection_is_stored_separately_from_customer_history(tmp_path):
    db = tmp_path / "bot.db"
    set_vip_protection(
        "100",
        _dt(2026, 11, 1),
        reason="合作老闆延長",
        operator_discord_id="200",
        operator_display_name="客服",
        db_file=db,
    )

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT protected_until, reason FROM vip_review_protections WHERE customer_id='100'"
        ).fetchone()

    assert row[0].startswith("2026-11-01")
    assert row[1] == "合作老闆延長"
