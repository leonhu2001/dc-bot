from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

from services.topups import (
    approve_topup_order,
    create_topup_order,
    get_pending_credit_topups,
    get_topup_order,
    mark_topup_processing,
    submit_topup_payment,
)
from services.wallet_refunds import (
    create_wallet_refund_request,
    list_pending_wallet_refunds,
    mark_wallet_refund_processing,
)
from services.wallet_service import adjust_wallet_balance


def _old_timestamp(minutes: int = 30) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_wallet_refund_queue_reclaims_only_stale_processing_jobs(tmp_path):
    db = tmp_path / "wallet-refund-recovery.db"

    for customer_id in ("101", "202"):
        adjust_wallet_balance(
            customer_id=customer_id,
            amount=1000,
            tx_type="topup",
            db_file=db,
        )

    stale = create_wallet_refund_request(
        customer_discord_id="101",
        amount=500,
        requested_by_discord_id="9",
        requested_by_display_name="Admin",
        db_file=db,
    )
    fresh = create_wallet_refund_request(
        customer_discord_id="202",
        amount=500,
        requested_by_discord_id="9",
        requested_by_display_name="Admin",
        db_file=db,
    )

    assert mark_wallet_refund_processing(int(stale["id"]), db_file=db)
    assert mark_wallet_refund_processing(int(fresh["id"]), db_file=db)

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE wallet_refund_requests SET processing_at=?, updated_at=? WHERE id=?",
            (_old_timestamp(), _old_timestamp(), int(stale["id"])),
        )
        conn.commit()

    queued = list_pending_wallet_refunds(
        stale_processing_minutes=10,
        db_file=db,
    )

    assert [int(row["id"]) for row in queued] == [int(stale["id"])]

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        stale_row = conn.execute(
            "SELECT status, processing_at, error_message FROM wallet_refund_requests WHERE id=?",
            (int(stale["id"]),),
        ).fetchone()
        fresh_row = conn.execute(
            "SELECT status FROM wallet_refund_requests WHERE id=?",
            (int(fresh["id"]),),
        ).fetchone()

    assert stale_row["status"] == "pending"
    assert stale_row["processing_at"] is None
    assert "自動重新排隊" in str(stale_row["error_message"] or "")
    assert fresh_row["status"] == "processing"


def _approved_topup(db, customer_id: str):
    row = create_topup_order(
        customer_discord_id=customer_id,
        customer_display_name=f"Boss-{customer_id}",
        amount=1000,
        source="web",
        db_file=db,
    )
    row = submit_topup_payment(
        int(row["id"]),
        customer_discord_id=customer_id,
        bank_last5="12345",
        db_file=db,
    )
    return approve_topup_order(
        int(row["id"]),
        operator_discord_id="9",
        operator_display_name="Admin",
        db_file=db,
    )


def test_topup_queue_reclaims_only_stale_crediting_jobs(tmp_path):
    db = tmp_path / "topup-recovery.db"
    stale = _approved_topup(db, "101")
    fresh = _approved_topup(db, "202")

    assert mark_topup_processing(int(stale["id"]), db_file=db)
    assert mark_topup_processing(int(fresh["id"]), db_file=db)

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE topup_orders SET updated_at=? WHERE id=?",
            (_old_timestamp(), int(stale["id"])),
        )
        conn.commit()

    queued = get_pending_credit_topups(
        stale_crediting_minutes=10,
        db_file=db,
    )

    assert [int(row["id"]) for row in queued] == [int(stale["id"])]
    assert get_topup_order(int(stale["id"]), db_file=db)["status"] == "approved_pending_credit"
    assert get_topup_order(int(fresh["id"]), db_file=db)["status"] == "crediting"
