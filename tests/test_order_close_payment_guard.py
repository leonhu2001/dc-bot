import pytest

from services.order_lifecycle_runtime import validate_order_ready_to_close
from services.payment_review_runtime import (
    _rejection_still_targets_current_order_review,
    _validate_order_review_snapshot,
)


@pytest.mark.parametrize(
    "status",
    [
        "pending_cs_dispatch",
        "waiting_acceptance",
        "accepted_pending_pay",
        "stored",
        "cancelled",
        "closed",
        "",
    ],
)
def test_order_close_guard_rejects_non_active_status(status):
    with pytest.raises(ValueError):
        validate_order_ready_to_close({"status": status, "amount": 1000})


def test_order_close_guard_allows_active_order():
    validate_order_ready_to_close({"status": "active", "amount": 1000})


def _review_row(**overrides):
    row = {
        "id": 88,
        "source_id": "123",
        "customer_discord_id": "999",
        "amount": 1000,
        "payment_method": "轉帳",
    }
    row.update(overrides)
    return row


def _runtime_order(**overrides):
    data = {
        "status": "accepted_pending_pay",
        "payment_review_id": 88,
        "web_order_id": 123,
        "customer_id": 999,
        "amount": 1000,
        "payment_method": "轉帳",
    }
    data.update(overrides)
    return data


def test_payment_review_snapshot_accepts_unchanged_order():
    _validate_order_review_snapshot(_review_row(), _runtime_order(), customer_id=999)


@pytest.mark.parametrize(
    ("runtime_change", "message"),
    [
        ({"amount": 1200}, "金額"),
        ({"payment_method": "街口"}, "付款方式"),
        ({"web_order_id": 456}, "所屬訂單"),
        ({"customer_id": 777}, "顧客"),
        ({"payment_review_id": 99}, "審核編號"),
        ({"status": "active"}, "不是等待付款"),
    ],
)
def test_payment_review_snapshot_rejects_stale_order(runtime_change, message):
    with pytest.raises(RuntimeError, match=message):
        _validate_order_review_snapshot(
            _review_row(),
            _runtime_order(**runtime_change),
            customer_id=999,
        )


def test_late_rejection_does_not_clear_newer_review():
    assert not _rejection_still_targets_current_order_review(
        _review_row(id=88),
        _runtime_order(payment_review_id=99),
    )


def test_late_rejection_does_not_clear_active_order():
    assert not _rejection_still_targets_current_order_review(
        _review_row(),
        _runtime_order(status="active"),
    )


def test_current_rejection_is_allowed_to_reset_payment_panel():
    assert _rejection_still_targets_current_order_review(
        _review_row(),
        _runtime_order(),
    )
