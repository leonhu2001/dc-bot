from pathlib import Path

import pytest

from services.payment_reviews import (
    PAYMENT_REVIEW_APPROVED,
    PAYMENT_REVIEW_APPLIED,
    PAYMENT_REVIEW_APPLY_ERROR,
    PAYMENT_REVIEW_PENDING,
    PAYMENT_REVIEW_REJECTED,
    approve_payment_review,
    create_payment_review,
    get_payment_review,
    list_payment_reviews,
    mark_payment_review_applied,
    mark_payment_review_apply_error,
    reject_payment_review,
    retry_payment_review_apply,
)


def test_order_payment_review_lifecycle(tmp_path: Path):
    db_file = tmp_path / "payments.db"

    review = create_payment_review(
        source_type="order",
        source_id=178,
        ticket_channel_id=1551613354500558928,
        customer_discord_id="123",
        customer_display_name="Boss",
        amount=2688,
        payment_method="轉帳",
        db_file=db_file,
    )

    assert review["status"] == PAYMENT_REVIEW_PENDING
    assert review["source_type"] == "order"
    assert review["source_id"] == "178"
    assert str(review["review_no"]).startswith("PAY-")

    approved = approve_payment_review(
        int(review["id"]),
        operator_discord_id="999",
        operator_display_name="Staff",
        db_file=db_file,
    )
    assert approved["status"] == PAYMENT_REVIEW_APPROVED

    mark_payment_review_applied(
        int(review["id"]),
        db_file=db_file,
    )

    stored = get_payment_review(int(review["id"]), db_file=db_file)
    assert stored is not None
    assert stored["status"] == PAYMENT_REVIEW_APPLIED
    assert stored["applied_at"]


def test_duplicate_pending_review_is_reused(tmp_path: Path):
    db_file = tmp_path / "payments.db"

    first = create_payment_review(
        source_type="worker_tip",
        source_id=5,
        ticket_channel_id=111,
        customer_discord_id="123",
        customer_display_name="Boss",
        target_discord_id="456",
        target_display_name="Worker",
        amount=500,
        payment_method="街口",
        db_file=db_file,
    )
    second = create_payment_review(
        source_type="worker_tip",
        source_id=5,
        ticket_channel_id=111,
        customer_discord_id="123",
        customer_display_name="Boss",
        target_discord_id="456",
        target_display_name="Worker",
        amount=500,
        payment_method="街口",
        db_file=db_file,
    )

    assert int(first["id"]) == int(second["id"])
    assert len(list_payment_reviews(db_file=db_file)) == 1


def test_rejected_review_allows_new_submission(tmp_path: Path):
    db_file = tmp_path / "payments.db"

    review = create_payment_review(
        source_type="order",
        source_id=10,
        ticket_channel_id=222,
        customer_discord_id="123",
        customer_display_name="Boss",
        amount=1000,
        payment_method="轉帳",
        db_file=db_file,
    )

    rejected = reject_payment_review(
        int(review["id"]),
        operator_discord_id="999",
        operator_display_name="Staff",
        reason="未確認到款項",
        db_file=db_file,
    )
    assert rejected["status"] == PAYMENT_REVIEW_REJECTED

    replacement = create_payment_review(
        source_type="order",
        source_id=10,
        ticket_channel_id=222,
        customer_discord_id="123",
        customer_display_name="Boss",
        amount=1000,
        payment_method="轉帳",
        db_file=db_file,
    )

    assert int(replacement["id"]) != int(review["id"])
    assert replacement["status"] == PAYMENT_REVIEW_PENDING


def test_apply_error_can_retry_or_reject(tmp_path: Path):
    db_file = tmp_path / "payments.db"

    review = create_payment_review(
        source_type="order",
        source_id=11,
        ticket_channel_id=333,
        customer_discord_id="123",
        customer_display_name="Boss",
        amount=1500,
        payment_method="街口",
        db_file=db_file,
    )
    approve_payment_review(
        int(review["id"]),
        operator_discord_id="999",
        operator_display_name="Staff",
        db_file=db_file,
    )

    mark_payment_review_apply_error(
        int(review["id"]),
        "Discord temporary error",
        db_file=db_file,
    )

    failed = get_payment_review(int(review["id"]), db_file=db_file)
    assert failed is not None
    assert failed["status"] == PAYMENT_REVIEW_APPLY_ERROR

    retried = retry_payment_review_apply(
        int(review["id"]),
        db_file=db_file,
    )
    assert retried["status"] == PAYMENT_REVIEW_APPROVED
    assert retried["apply_error"] is None


def test_only_external_methods_can_enter_review(tmp_path: Path):
    db_file = tmp_path / "payments.db"

    with pytest.raises(ValueError):
        create_payment_review(
            source_type="order",
            source_id=12,
            ticket_channel_id=444,
            customer_discord_id="123",
            customer_display_name="Boss",
            amount=1000,
            payment_method="我的錢包",
            db_file=db_file,
        )
