import inspect

import pytest

from services.order_lifecycle_runtime import validate_order_ready_to_close
from services.order_payment_runtime import finalize_accepted_pending_payment
from services.payment_review_runtime import (
    _rejection_still_targets_current_order_review,
    _release_stale_review_runtime_lock,
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


def test_payment_requires_canonical_web_order_before_any_payment_path():
    source = inspect.getsource(finalize_accepted_pending_payment)

    web_order_guard = source.index("if web_order_id is None:")
    external_review_branch = source.index("submit_external_payment_review_if_needed")
    wallet_debit_branch = source.index("if requires_wallet_debit")

    assert web_order_guard < external_review_branch
    assert web_order_guard < wallet_debit_branch


def test_member_reward_runs_only_after_canonical_order_promotion():
    source = inspect.getsource(finalize_accepted_pending_payment)

    promotion = source.index("promote_acceptance_claims_to_assignments")
    reward = source.index("reward_result = await add_customer_reward_from_order")

    assert promotion < reward


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
        "payment_review_no": "PAY-88",
        "payment_review_pending": True,
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


def test_stale_current_review_releases_pending_lock_for_resubmit():
    data = _runtime_order(amount=1200)

    changed = _release_stale_review_runtime_lock(
        _review_row(),
        data,
        "付款審核金額已過期",
    )

    assert changed is True
    assert data["payment_review_pending"] is False
    assert data["payment_review_approved"] is False
    assert data["payment_review_last_apply_error_id"] == 88
    assert "payment_review_id" not in data
    assert "payment_review_no" not in data


def test_stale_older_review_does_not_release_newer_review_lock():
    data = _runtime_order(payment_review_id=99, payment_review_no="PAY-99")

    changed = _release_stale_review_runtime_lock(
        _review_row(id=88),
        data,
        "舊審核",
    )

    assert changed is False
    assert data["payment_review_pending"] is True
    assert data["payment_review_id"] == 99
    assert data["payment_review_no"] == "PAY-99"


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
