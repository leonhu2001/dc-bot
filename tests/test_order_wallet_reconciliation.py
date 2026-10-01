import pytest

from services.order_wallet_reconciliation import (
    build_wallet_payment_adjustment_plan,
    expected_wallet_net_before_edit,
    validate_wallet_net_before_adjustment,
)


def test_wallet_amount_increase_creates_extra_charge():
    plan = build_wallet_payment_adjustment_plan(
        old_amount=652,
        new_amount=1152,
        old_payment_method="我的錢包",
        new_payment_method="我的錢包",
        old_customer_id="customer-1",
        new_customer_id="customer-1",
    )

    assert plan is not None
    assert plan["customer_id"] == "customer-1"
    assert plan["amount"] == -500
    assert plan["mode"] == "wallet_to_wallet"


def test_wallet_amount_decrease_creates_refund():
    plan = build_wallet_payment_adjustment_plan(
        old_amount=1300,
        new_amount=1274,
        old_payment_method="我的錢包",
        new_payment_method="我的錢包",
        old_customer_id="customer-1",
        new_customer_id="customer-1",
    )

    assert plan is not None
    assert plan["amount"] == 26


def test_switching_from_wallet_refunds_old_customer():
    plan = build_wallet_payment_adjustment_plan(
        old_amount=800,
        new_amount=1000,
        old_payment_method="我的錢包",
        new_payment_method="轉帳",
        old_customer_id="customer-1",
        new_customer_id="customer-2",
    )

    assert plan is not None
    assert plan["customer_id"] == "customer-1"
    assert plan["amount"] == 800
    assert plan["mode"] == "wallet_to_non_wallet"


def test_switching_to_wallet_charges_new_customer():
    plan = build_wallet_payment_adjustment_plan(
        old_amount=800,
        new_amount=1000,
        old_payment_method="轉帳",
        new_payment_method="我的錢包",
        old_customer_id="customer-1",
        new_customer_id="customer-2",
    )

    assert plan is not None
    assert plan["customer_id"] == "customer-2"
    assert plan["amount"] == -1000
    assert plan["mode"] == "non_wallet_to_wallet"


def test_wallet_customer_change_is_blocked():
    with pytest.raises(ValueError, match="禁止自動搬移"):
        build_wallet_payment_adjustment_plan(
            old_amount=800,
            new_amount=1000,
            old_payment_method="我的錢包",
            new_payment_method="我的錢包",
            old_customer_id="customer-1",
            new_customer_id="customer-2",
        )


def test_non_wallet_edit_needs_no_wallet_adjustment():
    plan = build_wallet_payment_adjustment_plan(
        old_amount=800,
        new_amount=1000,
        old_payment_method="轉帳",
        new_payment_method="街口",
        old_customer_id="customer-1",
        new_customer_id="customer-1",
    )

    assert plan is None


def test_expected_wallet_net_before_edit_uses_old_wallet_amount():
    assert (
        expected_wallet_net_before_edit(
            old_amount=652,
            old_payment_method="我的錢包",
        )
        == -652
    )

    assert (
        expected_wallet_net_before_edit(
            old_amount=652,
            old_payment_method="轉帳",
        )
        == 0
    )


def test_existing_wallet_drift_blocks_auto_adjustment():
    with pytest.raises(ValueError, match="禁止在既有差異上自動追加調整"):
        validate_wallet_net_before_adjustment(
            old_amount=1152,
            old_payment_method="我的錢包",
            actual_wallet_net=-652,
        )


def test_balanced_wallet_state_allows_auto_adjustment():
    validate_wallet_net_before_adjustment(
        old_amount=1152,
        old_payment_method="我的錢包",
        actual_wallet_net=-1152,
    )
