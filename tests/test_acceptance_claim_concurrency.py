from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import threading
import time

from sqlalchemy import create_engine, text

from shared import order_acceptance
from shared.order_state import WAITING_ACCEPTANCE


def test_concurrent_claims_cannot_overfill_or_raise_database_lock(tmp_path, monkeypatch):
    db_file = tmp_path / "acceptance-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    monkeypatch.setattr(order_acceptance, "engine", engine)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dispatch_message_id TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(
            text("""
                INSERT INTO web_orders(id, status, dispatch_message_id, updated_at)
                VALUES(1, :status, '999', CURRENT_TIMESTAMP)
            """),
            {"status": WAITING_ACCEPTANCE},
        )

    order_acceptance.create_or_update_acceptance_meta(
        order_id=1,
        order_rule_key="test_rule",
        required_staff_count=1,
        min_protector_count=0,
        allowed_role_ids=["100"],
        specified_staff_ids=[],
        status=WAITING_ACCEPTANCE,
    )
    unlocked_at = (
        datetime.now(UTC).replace(tzinfo=None)
        - timedelta(seconds=order_acceptance.PUBLIC_ACCEPTANCE_LOCK_SECONDS + 5)
    ).isoformat(timespec="seconds")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE order_acceptance_meta SET created_at=:created_at WHERE order_id=1"),
            {"created_at": unlocked_at},
        )

    original_active_claim_rows = order_acceptance._active_claim_rows
    start_barrier = threading.Barrier(2)
    thread_state = threading.local()

    def delayed_first_active_claim_read(conn, order_id):
        rows = original_active_claim_rows(conn, order_id)
        if not getattr(thread_state, "passed_first_read", False):
            thread_state.passed_first_read = True
            # Without a serialized write transaction both callers can read the
            # same empty slot during this window and then both insert. With
            # BEGIN IMMEDIATE the second caller cannot reach this read until
            # the first claim has committed.
            time.sleep(0.15)
        return rows

    monkeypatch.setattr(
        order_acceptance,
        "_active_claim_rows",
        delayed_first_active_claim_read,
    )

    def claim(staff_id: str):
        start_barrier.wait(timeout=5)
        try:
            state = order_acceptance.claim_acceptance_order(
                order_id=1,
                staff_discord_id=staff_id,
                staff_display_name=staff_id,
                staff_role_ids=["100"],
                source="web",
            )
            return ("ok", state.accepted_count)
        except Exception as exc:  # assertion below verifies the public failure type
            return (type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("A", "B")))

    monkeypatch.setattr(
        order_acceptance,
        "_active_claim_rows",
        original_active_claim_rows,
    )

    with engine.begin() as conn:
        active_count = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM order_acceptance_claims "
                    "WHERE order_id=1 AND is_active=1"
                )
            ).scalar_one()
        )

    assert active_count == 1
    assert sum(1 for result in results if result[0] == "ok") == 1
    rejected = [result for result in results if result[0] != "ok"]
    assert len(rejected) == 1
    assert rejected[0][0] == "ValueError"
    assert "滿人" in rejected[0][1]
