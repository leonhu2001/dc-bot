from __future__ import annotations

import sqlite3

import pytest

from core.vip_levels import get_topup_rebate_percent
from services.wallet_service import (
    adjust_wallet_balance,
    ensure_wallet_tables,
    get_refundable_wallet_balance,
    get_tip_eligible_wallet_balance,
    get_wallet_balance_breakdown,
)


def test_new_vip_topup_rebate_rates():
    assert get_topup_rebate_percent("白金魔丸") == 1
    assert get_topup_rebate_percent("鑽石魔丸") == 2
    assert get_topup_rebate_percent("白鑽魔丸") == 3
    assert get_topup_rebate_percent("黑鑽魔丸") == 3


def test_topup_principal_and_bonus_are_tracked_separately(tmp_path):
    db = tmp_path / "bot.db"

    adjust_wallet_balance(
        customer_id="1",
        amount=1000,
        tx_type="topup",
        order_no="TOPUP-1",
        db_file=db,
    )
    adjust_wallet_balance(
        customer_id="1",
        amount=30,
        tx_type="topup_bonus",
        order_no="TOPUP-1",
        db_file=db,
    )

    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 1030,
        "principal_balance": 1000,
        "bonus_balance": 30,
        "refund_offset_balance": 0,
        "refundable_balance": 1000,
    }


def test_normal_payment_spends_bonus_before_principal(tmp_path):
    db = tmp_path / "bot.db"
    adjust_wallet_balance(customer_id="1", amount=1000, tx_type="topup", db_file=db)
    adjust_wallet_balance(customer_id="1", amount=30, tx_type="topup_bonus", db_file=db)

    adjust_wallet_balance(
        customer_id="1",
        amount=-20,
        tx_type="payment",
        order_channel_id="123",
        db_file=db,
    )

    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 1010,
        "principal_balance": 1000,
        "bonus_balance": 10,
        "refund_offset_balance": 20,
        "refundable_balance": 980,
    }


def test_principal_spending_automatically_settles_used_bonus_refund_offset(tmp_path):
    db = tmp_path / "bot.db"
    adjust_wallet_balance(customer_id="1", amount=1000, tx_type="topup", db_file=db)
    adjust_wallet_balance(customer_id="1", amount=30, tx_type="topup_bonus", db_file=db)

    adjust_wallet_balance(customer_id="1", amount=-30, tx_type="payment", db_file=db)
    assert get_refundable_wallet_balance("1", db) == 970

    adjust_wallet_balance(customer_id="1", amount=-20, tx_type="payment", db_file=db)
    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 980,
        "principal_balance": 980,
        "bonus_balance": 0,
        "refund_offset_balance": 10,
        "refundable_balance": 970,
    }

    adjust_wallet_balance(customer_id="1", amount=-10, tx_type="payment", db_file=db)
    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 970,
        "principal_balance": 970,
        "bonus_balance": 0,
        "refund_offset_balance": 0,
        "refundable_balance": 970,
    }


def test_tip_cannot_use_bonus_balance_but_can_use_cash_backed_principal(tmp_path):
    db = tmp_path / "bot.db"
    adjust_wallet_balance(customer_id="1", amount=100, tx_type="topup", db_file=db)
    adjust_wallet_balance(customer_id="1", amount=20, tx_type="topup_bonus", db_file=db)

    # 總額 120T，但雞腿只能動用 100T 實付本金。
    with pytest.raises(ValueError, match="雞腿只能使用實付本金"):
        adjust_wallet_balance(
            customer_id="1",
            amount=-110,
            tx_type="tip_payment",
            order_no="ORDER-1:TIP-1",
            db_file=db,
        )

    # 一般點單先花 20T 贈額後，本金仍可拿來雞腿；
    # 這筆本金消費同時會沖掉先前形成的 20T 退款抵扣額。
    adjust_wallet_balance(customer_id="1", amount=-20, tx_type="payment", db_file=db)
    assert get_tip_eligible_wallet_balance("1", db) == 100
    assert get_refundable_wallet_balance("1", db) == 80

    adjust_wallet_balance(
        customer_id="1",
        amount=-20,
        tx_type="tip_payment",
        order_no="ORDER-1:TIP-2",
        db_file=db,
    )
    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 80,
        "principal_balance": 80,
        "bonus_balance": 0,
        "refund_offset_balance": 0,
        "refundable_balance": 80,
    }


def test_refund_debit_never_uses_bonus_balance(tmp_path):
    db = tmp_path / "bot.db"
    adjust_wallet_balance(customer_id="1", amount=100, tx_type="topup", db_file=db)
    adjust_wallet_balance(customer_id="1", amount=20, tx_type="topup_bonus", db_file=db)

    adjust_wallet_balance(customer_id="1", amount=-80, tx_type="refund", db_file=db)
    assert get_wallet_balance_breakdown("1", db) == {
        "balance": 40,
        "principal_balance": 20,
        "bonus_balance": 20,
        "refund_offset_balance": 0,
        "refundable_balance": 20,
    }

    with pytest.raises(ValueError, match="可退款實付本金不足"):
        adjust_wallet_balance(customer_id="1", amount=-30, tx_type="refund", db_file=db)


def test_legacy_wallet_balance_is_bootstrapped_as_principal(tmp_path):
    db = tmp_path / "bot.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO customer_wallets(customer_discord_id, balance) VALUES('legacy', 777)"
        )
        conn.commit()

    ensure_wallet_tables(db)

    assert get_wallet_balance_breakdown("legacy", db) == {
        "balance": 777,
        "principal_balance": 777,
        "bonus_balance": 0,
        "refund_offset_balance": 0,
        "refundable_balance": 777,
    }
