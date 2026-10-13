from pathlib import Path

import pytest

from services.wallet_service import (
    adjust_wallet_balance,
    get_wallet_balance,
    get_wallet_transactions,
)


def test_bot_delegates_wallet_persistence_to_canonical_service():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    service_source = Path("services/wallet_service.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS customer_wallets" not in bot_source
    assert "CREATE TABLE IF NOT EXISTS wallet_transactions" not in bot_source
    assert "SELECT balance FROM customer_wallets" not in bot_source
    assert "INSERT INTO wallet_transactions" not in bot_source
    assert "_wallet_adjust_balance(" in bot_source
    assert "_wallet_get_transactions(" in bot_source

    assert "CREATE TABLE IF NOT EXISTS customer_wallets" in service_source
    assert "CREATE TABLE IF NOT EXISTS wallet_transactions" in service_source
    assert "BEGIN IMMEDIATE" in service_source
    assert "def get_wallet_transactions(" in service_source


def test_canonical_wallet_reference_is_idempotent_and_queryable(tmp_path):
    db_file = tmp_path / "bot.db"
    adjust_wallet_balance(
        customer_id="customer-1",
        amount=2000,
        tx_type="topup",
        order_no="TOPUP-1",
        db_file=db_file,
    )
    first = adjust_wallet_balance(
        customer_id="customer-1",
        amount=-350,
        tx_type="payment",
        order_no="ORDER-1",
        order_channel_id="ticket-1",
        db_file=db_file,
    )
    second = adjust_wallet_balance(
        customer_id="customer-1",
        amount=-350,
        tx_type="payment",
        order_no="ORDER-1",
        order_channel_id="ticket-1",
        db_file=db_file,
    )

    assert first["id"] == second["id"]
    assert get_wallet_balance("customer-1", db_file) == 1650
    rows = get_wallet_transactions("customer-1", limit=10, db_file=db_file)
    assert [row["type"] for row in rows] == ["payment", "topup"]
    assert rows[0]["order_no"] == "ORDER-1"

    with pytest.raises(ValueError, match="金額不同"):
        adjust_wallet_balance(
            customer_id="customer-1",
            amount=-351,
            tx_type="payment",
            order_no="ORDER-1",
            db_file=db_file,
        )


def test_wallet_rejects_overdraft_with_customer_facing_amounts(tmp_path):
    db_file = tmp_path / "bot.db"
    with pytest.raises(ValueError) as exc_info:
        adjust_wallet_balance(
            customer_id="customer-2",
            amount=-500,
            tx_type="payment",
            order_no="ORDER-2",
            db_file=db_file,
        )

    message = str(exc_info.value)
    assert "目前餘額 0T" in message
    assert "無法扣除 500T" in message
