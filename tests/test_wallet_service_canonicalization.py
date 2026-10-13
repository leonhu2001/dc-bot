from pathlib import Path

import pytest

from services.wallet_service import (
    adjust_wallet_balance,
    get_wallet_balance,
    get_wallet_payment_transaction,
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


def test_wallet_payment_without_order_no_is_idempotent_by_ticket_channel(tmp_path):
    db_file = tmp_path / "bot.db"
    adjust_wallet_balance(
        customer_id="customer-channel",
        amount=2867,
        tx_type="topup",
        db_file=db_file,
    )

    first = adjust_wallet_balance(
        customer_id="customer-channel",
        amount=-1529,
        tx_type="payment",
        order_channel_id="ticket-1013",
        order_no=None,
        db_file=db_file,
    )
    # Simulate the dangerous crash window: debit committed but the order's
    # wallet_transaction_id marker was never persisted. A retry supplies only the
    # same ticket channel and must recover, not debit again.
    retry = adjust_wallet_balance(
        customer_id="customer-channel",
        amount=-1529,
        tx_type="payment",
        order_channel_id="ticket-1013",
        order_no=None,
        db_file=db_file,
    )

    assert retry["id"] == first["id"]
    assert retry["idempotent_replay"] is True
    assert get_wallet_balance("customer-channel", db_file) == 1338
    ledger = get_wallet_payment_transaction(
        "customer-channel",
        "ticket-1013",
        db_file=db_file,
    )
    assert ledger is not None
    assert ledger["id"] == first["id"]
    assert ledger["balance_after"] == 1338
    payment_rows = [
        row
        for row in get_wallet_transactions("customer-channel", limit=10, db_file=db_file)
        if row["type"] == "payment"
    ]
    assert len(payment_rows) == 1

    with pytest.raises(ValueError, match="同一訂單票口已有不同金額"):
        adjust_wallet_balance(
            customer_id="customer-channel",
            amount=-1500,
            tx_type="payment",
            order_channel_id="ticket-1013",
            order_no=None,
            db_file=db_file,
        )


def test_wallet_payment_panel_recovers_committed_debit_instead_of_previewing_second_debit():
    source = Path("services/order_runtime.py").read_text(encoding="utf-8")
    assert "get_wallet_payment_transaction(" in source
    assert "✅ 錢包已扣款" in source
    assert "重新送出只會繼續完成訂單，不會再次扣款" in source

    runtime = Path("services/order_payment_runtime.py").read_text(encoding="utf-8")
    assert 'if not wallet_tx.get("idempotent_replay")' in runtime
