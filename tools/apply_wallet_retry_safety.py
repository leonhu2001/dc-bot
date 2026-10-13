from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}\n--- needle ---\n{old[:500]}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Make Discord order wallet debits DB-idempotent by ticket channel, not only by
# a receipt/order number that does not exist yet at acceptance-payment time.
replace_once(
    "services/wallet_service.py",
    '''        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference "
            "ON wallet_transactions(customer_discord_id, order_no, type)"
        )

        # Even if historical duplicate references already exist, this trigger blocks
''',
    '''        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference "
            "ON wallet_transactions(customer_discord_id, order_no, type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_payment_channel "
            "ON wallet_transactions(customer_discord_id, order_channel_id, type)"
        )

        # Acceptance-payment wallet debits happen before a formal receipt/order_no
        # exists. The ticket channel is therefore the stable payment idempotency key.
        # Keep this as a trigger (rather than a unique-index migration) so historical
        # duplicate rows, if any, do not make startup fail while all future duplicate
        # debits are still blocked.
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_wallet_tx_unique_payment_channel
            BEFORE INSERT ON wallet_transactions
            WHEN NEW.type = 'payment'
              AND NEW.order_channel_id IS NOT NULL
              AND TRIM(NEW.order_channel_id) <> ''
              AND EXISTS (
                  SELECT 1
                  FROM wallet_transactions
                  WHERE customer_discord_id = NEW.customer_discord_id
                    AND order_channel_id = NEW.order_channel_id
                    AND type = 'payment'
              )
            BEGIN
                SELECT RAISE(ABORT, 'duplicate wallet payment channel');
            END
            """
        )

        # Even if historical duplicate references already exist, this trigger blocks
''',
)

replace_once(
    "services/wallet_service.py",
    '''def get_wallet_transactions(
''',
    '''def get_wallet_payment_transaction(
    customer_id: str | int,
    order_channel_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the original wallet debit for a Discord order ticket, if any."""
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM wallet_transactions
            WHERE customer_discord_id=?
              AND order_channel_id=?
              AND type='payment'
            ORDER BY id ASC
            LIMIT 1
            """,
            (str(customer_id), str(order_channel_id)),
        ).fetchone()
        return dict(row) if row else None


def get_wallet_transactions(
''',
)

replace_once(
    "services/wallet_service.py",
    '''    normalized_order_no = str(order_no or "").strip() or None
    normalized_type = str(tx_type)

    with sqlite3.connect(path, timeout=15) as conn:
''',
    '''    normalized_order_no = str(order_no or "").strip() or None
    normalized_order_channel_id = str(order_channel_id or "").strip() or None
    normalized_type = str(tx_type)

    with sqlite3.connect(path, timeout=15) as conn:
''',
)

replace_once(
    "services/wallet_service.py",
    '''        # Idempotency check must happen inside the same write transaction and before
        # balance calculation. Repeated delivery of the same reference returns the
        # original transaction instead of crediting/debiting a second time.
        if normalized_order_no:
''',
    '''        # Idempotency checks must happen inside the same write transaction and before
        # balance calculation. A Discord order payment is keyed by ticket channel because
        # the formal receipt/order number is generated only after wallet debit succeeds.
        if normalized_type == "payment" and normalized_order_channel_id:
            existing = conn.execute(
                """
                SELECT *
                FROM wallet_transactions
                WHERE customer_discord_id=? AND order_channel_id=? AND type='payment'
                ORDER BY id ASC
                LIMIT 1
                """,
                (str(customer_id), normalized_order_channel_id),
            ).fetchone()

            if existing is not None:
                if int(existing["amount"] or 0) != amount:
                    raise ValueError(
                        "同一訂單票口已有不同金額的錢包扣款；已拒絕再次扣款，請通知客服確認。"
                    )
                conn.rollback()
                result = dict(existing)
                result["idempotent_replay"] = True
                return result

        # Non-order flows and legacy callers can still use the formal reference key.
        if normalized_order_no:
''',
)

replace_once(
    "services/wallet_service.py",
    '''                conn.rollback()
                return dict(existing)

        row = conn.execute(
''',
    '''                conn.rollback()
                result = dict(existing)
                result["idempotent_replay"] = True
                return result

        row = conn.execute(
''',
)

replace_once(
    "services/wallet_service.py",
    '''                str(order_channel_id) if order_channel_id is not None else None,
                normalized_order_no,
''',
    '''                normalized_order_channel_id,
                normalized_order_no,
''',
)

replace_once(
    "services/wallet_service.py",
    '''            "order_channel_id": (
                str(order_channel_id)
                if order_channel_id is not None
                else None
            ),
            "note": note,
            "created_at": now_text,
        }
''',
    '''            "order_channel_id": normalized_order_channel_id,
            "note": note,
            "created_at": now_text,
            "idempotent_replay": False,
        }
''',
)

# 2) Payment selector self-heals a lost order-data marker from the canonical wallet
# ledger and shows an already-paid state instead of subtracting the order again.
replace_once(
    "services/order_runtime.py",
    '''from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
''',
    '''from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services.wallet_service import get_wallet_payment_transaction
''',
)

old_wallet_panel = '''            if selected_method == WALLET_PAYMENT_METHOD:
                wallet_balance = get_wallet_balance(self.customer_id)
                if amount > 0:
                    after_balance = wallet_balance - amount
                    wallet_text = (
                        f"目前錢包餘額：{format_t_amount(wallet_balance)}\\n"
                        f"本單金額：{format_t_amount(amount)}\\n"
                    )
                    if after_balance >= 0:
                        wallet_text += f"扣款後餘額：{format_t_amount(after_balance)}"
                    else:
                        wallet_text += f"尚不足：{format_t_amount(abs(after_balance))}"
                else:
                    wallet_text = (
                        f"目前錢包餘額：{format_t_amount(wallet_balance)}\\n"
                        "本單金額：待客服填寫"
                    )

                payment_embed.add_field(
                    name="我的錢包",
                    value=wallet_text,
                    inline=False,
                )
'''
new_wallet_panel = '''            if selected_method == WALLET_PAYMENT_METHOD:
                # A wallet debit may already have committed even if a later Discord/Web
                # finalization step failed. Recover the authoritative ledger row by ticket
                # channel so the UI and the next retry both know this order is already paid.
                wallet_tx = get_wallet_payment_transaction(
                    self.customer_id,
                    self.channel_id,
                    db_file=DB_FILE,
                )
                if wallet_tx is not None:
                    data["wallet_transaction_id"] = wallet_tx["id"]
                    data["wallet_paid_amount"] = abs(int(wallet_tx.get("amount") or 0))
                    data["wallet_balance_before"] = int(wallet_tx.get("balance_before") or 0)
                    data["wallet_balance_after"] = int(wallet_tx.get("balance_after") or 0)
                    remember_order_data(self.channel_id, data)
                    wallet_text = (
                        f"✅ 錢包已扣款：{format_t_amount(abs(int(wallet_tx.get('amount') or 0)))}\\n"
                        f"扣款後餘額：{format_t_amount(int(wallet_tx.get('balance_after') or 0))}\\n"
                        "重新送出只會繼續完成訂單，不會再次扣款。"
                    )
                else:
                    wallet_balance = get_wallet_balance(self.customer_id)
                    if amount > 0:
                        after_balance = wallet_balance - amount
                        wallet_text = (
                            f"目前錢包餘額：{format_t_amount(wallet_balance)}\\n"
                            f"本單金額：{format_t_amount(amount)}\\n"
                        )
                        if after_balance >= 0:
                            wallet_text += f"扣款後餘額：{format_t_amount(after_balance)}"
                        else:
                            wallet_text += f"尚不足：{format_t_amount(abs(after_balance))}"
                    else:
                        wallet_text = (
                            f"目前錢包餘額：{format_t_amount(wallet_balance)}\\n"
                            "本單金額：待客服填寫"
                        )

                payment_embed.add_field(
                    name="我的錢包",
                    value=wallet_text,
                    inline=False,
                )
'''
replace_once("services/order_runtime.py", old_wallet_panel, new_wallet_panel)

# 3) If the DB service recovered an already-committed debit, persist its markers but
# do not emit a second wallet audit/log message.
replace_once(
    "services/order_payment_runtime.py",
    '''                data["wallet_transaction_id"] = wallet_tx["id"]
                data["wallet_paid_amount"] = amount
                data["wallet_balance_before"] = wallet_tx["balance_before"]
                data["wallet_balance_after"] = wallet_tx["balance_after"]
                remember_order_data(channel_id, data)

                await send_wallet_log(
                    guild,
                    title="錢包訂單扣款",
                    customer=customer_member if customer_member is not None else interaction.user,
                    operator=interaction.user,
                    tx=wallet_tx,
                )
''',
    '''                data["wallet_transaction_id"] = wallet_tx["id"]
                data["wallet_paid_amount"] = abs(int(wallet_tx.get("amount") or amount))
                data["wallet_balance_before"] = wallet_tx["balance_before"]
                data["wallet_balance_after"] = wallet_tx["balance_after"]
                remember_order_data(channel_id, data)

                if not wallet_tx.get("idempotent_replay"):
                    await send_wallet_log(
                        guild,
                        title="錢包訂單扣款",
                        customer=customer_member if customer_member is not None else interaction.user,
                        operator=interaction.user,
                        tx=wallet_tx,
                    )
''',
)

# 4) Ledger-level and UI contract regressions.
p = Path("tests/test_wallet_service_canonicalization.py")
text = p.read_text(encoding="utf-8")
text = text.replace(
    '''    get_wallet_balance,\n    get_wallet_transactions,\n''',
    '''    get_wallet_balance,\n    get_wallet_payment_transaction,\n    get_wallet_transactions,\n''',
    1,
)
text += '''\n\ndef test_wallet_payment_without_order_no_is_idempotent_by_ticket_channel(tmp_path):
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
'''
p.write_text(text, encoding="utf-8")

# Keep reconciliation on the same canonical label owner while touching this area.
reconcile = Path("services/order_wallet_reconciliation.py")
reconcile_text = reconcile.read_text(encoding="utf-8")
if 'WALLET_PAYMENT_METHOD = "我的錢包"' in reconcile_text:
    reconcile_text = reconcile_text.replace(
        'WALLET_PAYMENT_METHOD = "我的錢包"',
        'from services.payment_methods import WALLET_PAYMENT_METHOD',
        1,
    )
    reconcile.write_text(reconcile_text, encoding="utf-8")

print("wallet retry safety patch applied")
