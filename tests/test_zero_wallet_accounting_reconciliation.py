import sqlite3

from web.app.services.accounting_reconciliation import _check_wallet_paid_orders


def _web_connection(*, customer_pay_amount: int) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE web_orders (
            id INTEGER PRIMARY KEY,
            bot_order_no TEXT,
            customer_discord_id TEXT,
            ticket_channel_id TEXT,
            amount INTEGER NOT NULL,
            customer_pay_amount INTEGER,
            payment_method TEXT,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO web_orders(
            id,
            bot_order_no,
            customer_discord_id,
            ticket_channel_id,
            amount,
            customer_pay_amount,
            payment_method,
            status
        ) VALUES(1, 'MO-ZERO-1', 'customer-1', 'ticket-1', ?, ?, '我的錢包', 'active')
        """,
        (customer_pay_amount, customer_pay_amount),
    )
    conn.commit()
    return conn


def test_zero_pay_wallet_order_does_not_require_fake_payment_transaction():
    conn = _web_connection(customer_pay_amount=0)
    issues = []
    try:
        _check_wallet_paid_orders(conn, {}, {}, issues)
    finally:
        conn.close()

    assert issues == []


def test_positive_wallet_order_still_requires_payment_transaction():
    conn = _web_connection(customer_pay_amount=200)
    issues = []
    try:
        _check_wallet_paid_orders(conn, {}, {}, issues)
    finally:
        conn.close()

    assert [issue["code"] for issue in issues] == ["wallet_order_tx_missing"]
    assert issues[0]["expected"] == -200
