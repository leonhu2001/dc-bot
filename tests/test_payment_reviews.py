from __future__ import annotations

import sqlite3

import pytest

from services.payment_reviews import (
    APPROVED_PENDING_APPLY,
    PENDING_REVIEW,
    REJECTED,
    approve_payment_review,
    create_or_resubmit_payment_review,
    ensure_payment_review_tables,
    get_payment_review,
    mark_payment_review_rejected_applied,
    reject_payment_review,
)


def test_order_payment_review_can_be_rejected_and_resubmitted(tmp_path):
    db = tmp_path / "web_dashboard.db"
    ensure_payment_review_tables(db)

    first = create_or_resubmit_payment_review(
        review_type="order",
        reference_id=178,
        order_id=178,
        ticket_channel_id="123456",
        customer_discord_id="999",
        customer_display_name="Boss",
        amount=2688,
        payment_method="轉帳",
        db_file=db,
    )

    assert first["status"] == PENDING_REVIEW
    review_id = int(first["id"])

    rejected_pending = reject_payment_review(
        review_id,
        operator_discord_id="111",
        operator_display_name="CS",
        reason="未看到付款截圖",
        db_file=db,
    )
    assert rejected_pending["status"] == "rejected_pending_apply"

    mark_payment_review_rejected_applied(review_id, db_file=db)
    assert get_payment_review(review_id, db_file=db)["status"] == REJECTED

    second = create_or_resubmit_payment_review(
        review_type="order",
        reference_id=178,
        order_id=178,
        ticket_channel_id="123456",
        customer_discord_id="999",
        customer_display_name="Boss",
        amount=2688,
        payment_method="街口",
        db_file=db,
    )

    assert int(second["id"]) == review_id
    assert second["status"] == PENDING_REVIEW
    assert second["payment_method"] == "街口"
    assert second["rejected_reason"] is None


def test_approved_review_cannot_be_submitted_twice(tmp_path):
    db = tmp_path / "web_dashboard.db"

    row = create_or_resubmit_payment_review(
        review_type="tip",
        reference_id=12,
        order_id=178,
        ticket_channel_id="123456",
        customer_discord_id="999",
        customer_display_name="Boss",
        amount=500,
        payment_method="街口",
        db_file=db,
    )

    approved = approve_payment_review(
        int(row["id"]),
        operator_discord_id="111",
        operator_display_name="CS",
        db_file=db,
    )
    assert approved["status"] == APPROVED_PENDING_APPLY

    with pytest.raises(ValueError):
        create_or_resubmit_payment_review(
            review_type="tip",
            reference_id=12,
            order_id=178,
            ticket_channel_id="123456",
            customer_discord_id="999",
            customer_display_name="Boss",
            amount=500,
            payment_method="街口",
            db_file=db,
        )


def test_review_source_is_unique(tmp_path):
    db = tmp_path / "web_dashboard.db"
    ensure_payment_review_tables(db)

    create_or_resubmit_payment_review(
        review_type="order",
        reference_id=1,
        order_id=1,
        ticket_channel_id="1",
        customer_discord_id="2",
        customer_display_name="Boss",
        amount=100,
        payment_method="轉帳",
        db_file=db,
    )

    with sqlite3.connect(db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM payment_reviews WHERE review_type='order' AND reference_id=1"
        ).fetchone()[0]

    assert count == 1
