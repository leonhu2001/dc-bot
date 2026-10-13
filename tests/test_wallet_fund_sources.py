from pathlib import Path

import pytest

from services.wallet_service import (
    adjust_wallet_balance,
    get_wallet_fund_breakdown,
)


def _credit(
    db_file: Path,
    *,
    customer_id: str,
    amount: int,
    tx_type: str,
    order_no: str,
) -> None:
    adjust_wallet_balance(
        customer_id=customer_id,
        amount=amount,
        tx_type=tx_type,
        order_no=order_no,
        db_file=db_file,
    )


def test_topup_principal_and_bonus_are_separated(tmp_path: Path):
    db_file = tmp_path / "wallet.db"
    _credit(
        db_file,
        customer_id="100",
        amount=1000,
        tx_type="topup",
        order_no="TOPUP-1",
    )
    _credit(
        db_file,
        customer_id="100",
        amount=30,
        tx_type="topup_bonus",
        order_no="TOPUP-1-BONUS",
    )

    funds = get_wallet_fund_breakdown("100", db_file=db_file)
    assert funds == {
        "balance": 1030,
        "refundable_principal": 1000,
        "nonrefundable_credit": 30,
    }


def test_normal_spending_consumes_paid_principal_first(tmp_path: Path):
    db_file = tmp_path / "wallet.db"
    _credit(
        db_file,
        customer_id="200",
        amount=1000,
        tx_type="topup",
        order_no="TOPUP-2",
    )
    _credit(
        db_file,
        customer_id="200",
        amount=30,
        tx_type="topup_bonus",
        order_no="TOPUP-2-BONUS",
    )

    adjust_wallet_balance(
        customer_id="200",
        amount=-400,
        tx_type="payment",
        order_channel_id="ticket-200",
        db_file=db_file,
    )

    funds = get_wallet_fund_breakdown("200", db_file=db_file)
    assert funds == {
        "balance": 630,
        "refundable_principal": 600,
        "nonrefundable_credit": 30,
    }


def test_tip_cannot_spend_topup_bonus(tmp_path: Path):
    db_file = tmp_path / "wallet.db"
    _credit(
        db_file,
        customer_id="300",
        amount=1000,
        tx_type="topup",
        order_no="TOPUP-3",
    )
    _credit(
        db_file,
        customer_id="300",
        amount=30,
        tx_type="topup_bonus",
        order_no="TOPUP-3-BONUS",
    )

    adjust_wallet_balance(
        customer_id="300",
        amount=-1000,
        tx_type="tip_payment",
        order_no="TIP-1",
        db_file=db_file,
    )

    with pytest.raises(ValueError, match="只能使用實付儲值本金"):
        adjust_wallet_balance(
            customer_id="300",
            amount=-1,
            tx_type="tip_payment",
            order_no="TIP-2",
            db_file=db_file,
        )

    funds = get_wallet_fund_breakdown("300", db_file=db_file)
    assert funds["balance"] == 30
    assert funds["refundable_principal"] == 0
    assert funds["nonrefundable_credit"] == 30


def test_manual_or_legacy_credit_is_not_refundable_principal(tmp_path: Path):
    db_file = tmp_path / "wallet.db"
    _credit(
        db_file,
        customer_id="400",
        amount=500,
        tx_type="manual_adjustment",
        order_no="MANUAL-1",
    )

    funds = get_wallet_fund_breakdown("400", db_file=db_file)
    assert funds["refundable_principal"] == 0
    assert funds["nonrefundable_credit"] == 500

    with pytest.raises(ValueError, match="只能使用實付儲值本金"):
        adjust_wallet_balance(
            customer_id="400",
            amount=-100,
            tx_type="tip_payment",
            order_no="TIP-3",
            db_file=db_file,
        )


def test_bonus_reversal_consumes_nonrefundable_credit_first(tmp_path: Path):
    db_file = tmp_path / "wallet.db"
    _credit(
        db_file,
        customer_id="500",
        amount=1000,
        tx_type="topup",
        order_no="TOPUP-5",
    )
    _credit(
        db_file,
        customer_id="500",
        amount=30,
        tx_type="topup_bonus",
        order_no="TOPUP-5-BONUS",
    )

    adjust_wallet_balance(
        customer_id="500",
        amount=-30,
        tx_type="topup_bonus_reversal",
        order_no="TOPUP-5-BONUS-REVERSAL",
        db_file=db_file,
    )

    funds = get_wallet_fund_breakdown("500", db_file=db_file)
    assert funds == {
        "balance": 1000,
        "refundable_principal": 1000,
        "nonrefundable_credit": 0,
    }
