from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot.py"
WALLET = ROOT / "services" / "wallet_service.py"
BUDGET = ROOT / "tests" / "test_architecture_growth_budget.py"
TEST = ROOT / "tests" / "test_wallet_service_canonicalization.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing marker for {label}")
    if text.count(old) != 1:
        raise RuntimeError(f"marker for {label} is not unique: {text.count(old)}")
    return text.replace(old, new, 1)


def update_wallet_service() -> None:
    text = WALLET.read_text(encoding="utf-8")
    if "def get_wallet_transactions(" not in text:
        marker = "\n\ndef adjust_wallet_balance(\n"
        addition = '''\n\ndef get_wallet_transactions(\n    customer_id: str | int,\n    *,\n    limit: int = 10,\n    db_file: str | Path | None = None,\n) -> list[dict[str, Any]]:\n    \"\"\"Return newest wallet transactions for one customer.\n\n    Persistence stays centralized here so Discord/Web callers do not open the\n    wallet tables independently.\n    \"\"\"\n    ensure_wallet_tables(db_file)\n    path = _db_path(db_file)\n    safe_limit = max(1, min(int(limit or 10), 25))\n    with sqlite3.connect(path, timeout=15) as conn:\n        conn.row_factory = sqlite3.Row\n        rows = conn.execute(\n            \"\"\"\n            SELECT\n                id, customer_discord_id, amount, balance_before, balance_after,\n                type, order_channel_id, order_no, operator_discord_id,\n                operator_display_name, note, created_at\n            FROM wallet_transactions\n            WHERE customer_discord_id = ?\n            ORDER BY id DESC\n            LIMIT ?\n            \"\"\",\n            (str(customer_id), safe_limit),\n        ).fetchall()\n        return [dict(row) for row in rows]\n'''
        text = replace_once(text, marker, addition + marker, label="wallet transactions insertion")

    old_error = 'raise ValueError(f"錢包餘額不足，目前餘額 {before:,}T。")'
    new_error = 'raise ValueError(\n                f"錢包餘額不足，目前餘額 {before:,}T，"\n                f"無法扣除 {abs(amount):,}T。"\n            )'
    if old_error in text:
        text = text.replace(old_error, new_error, 1)

    WALLET.write_text(text, encoding="utf-8")


def update_bot() -> None:
    text = BOT.read_text(encoding="utf-8")
    import_marker = '''from services.order_discounts import (\n    allocate_store_absorbed_fixed_discount,\n)\n'''
    wallet_import = '''from services.order_discounts import (\n    allocate_store_absorbed_fixed_discount,\n)\nfrom services.wallet_service import (\n    ensure_wallet_tables as _wallet_ensure_tables,\n    get_wallet_balance as _wallet_get_balance,\n    get_wallet_transactions as _wallet_get_transactions,\n    adjust_wallet_balance as _wallet_adjust_balance,\n)\n'''
    if "from services.wallet_service import (" not in text:
        text = replace_once(text, import_marker, wallet_import, label="wallet service import")

    start = text.index("def ensure_wallet_tables() -> None:\n")
    end = text.index("async def process_worker_tip_wallet_payment(\n", start)
    adapter = '''def ensure_wallet_tables() -> None:\n    \"\"\"Compatibility adapter: wallet schema ownership lives in wallet_service.\"\"\"\n    _wallet_ensure_tables(DB_FILE)\n\n\ndef get_wallet_balance(customer_id) -> int:\n    return _wallet_get_balance(customer_id, DB_FILE)\n\n\ndef adjust_customer_wallet_balance(\n    *,\n    customer_id,\n    amount: int,\n    tx_type: str,\n    operator=None,\n    order_channel_id=None,\n    order_no=None,\n    note: str | None = None,\n    allow_negative: bool = False,\n) -> dict:\n    \"\"\"Discord-facing adapter around the canonical wallet transaction service.\"\"\"\n    operator_id = getattr(operator, \"id\", None)\n    operator_name = (\n        getattr(operator, \"display_name\", None)\n        or getattr(operator, \"name\", None)\n        or (str(operator_id) if operator_id is not None else None)\n    )\n    normalized_type = str(tx_type or \"adjustment\").strip() or \"adjustment\"\n    return _wallet_adjust_balance(\n        customer_id=customer_id,\n        amount=amount,\n        tx_type=normalized_type,\n        operator_discord_id=operator_id,\n        operator_display_name=operator_name,\n        order_channel_id=order_channel_id,\n        order_no=order_no,\n        note=note,\n        allow_negative=allow_negative,\n        db_file=DB_FILE,\n    )\n\n\n'''
    text = text[:start] + adapter + text[end:]

    tx_start = text.index("def get_wallet_transactions(customer_id, limit: int = 10) -> list[dict]:\n")
    tx_end = text.index("def wallet_transaction_type_label(tx_type: str) -> str:\n", tx_start)
    tx_adapter = '''def get_wallet_transactions(customer_id, limit: int = 10) -> list[dict]:\n    return _wallet_get_transactions(customer_id, limit=limit, db_file=DB_FILE)\n\n\n'''
    text = text[:tx_start] + tx_adapter + text[tx_end:]

    BOT.write_text(text, encoding="utf-8")


def update_budget() -> None:
    text = BUDGET.read_text(encoding="utf-8")
    text = text.replace('"bot.py": 273_000,', '"bot.py": 267_000,', 1)
    BUDGET.write_text(text, encoding="utf-8")


def write_test() -> None:
    TEST.write_text('''from pathlib import Path\n\nimport pytest\n\nfrom services.wallet_service import (\n    adjust_wallet_balance,\n    get_wallet_balance,\n    get_wallet_transactions,\n)\n\n\ndef test_bot_delegates_wallet_persistence_to_canonical_service():\n    bot_source = Path("bot.py").read_text(encoding="utf-8")\n    service_source = Path("services/wallet_service.py").read_text(encoding="utf-8")\n\n    assert "CREATE TABLE IF NOT EXISTS customer_wallets" not in bot_source\n    assert "CREATE TABLE IF NOT EXISTS wallet_transactions" not in bot_source\n    assert "SELECT balance FROM customer_wallets" not in bot_source\n    assert "INSERT INTO wallet_transactions" not in bot_source\n    assert "_wallet_adjust_balance(" in bot_source\n    assert "_wallet_get_transactions(" in bot_source\n\n    assert "CREATE TABLE IF NOT EXISTS customer_wallets" in service_source\n    assert "CREATE TABLE IF NOT EXISTS wallet_transactions" in service_source\n    assert "BEGIN IMMEDIATE" in service_source\n    assert "def get_wallet_transactions(" in service_source\n\n\ndef test_canonical_wallet_reference_is_idempotent_and_queryable(tmp_path):\n    db_file = tmp_path / "bot.db"\n    adjust_wallet_balance(\n        customer_id="customer-1",\n        amount=2000,\n        tx_type="topup",\n        order_no="TOPUP-1",\n        db_file=db_file,\n    )\n    first = adjust_wallet_balance(\n        customer_id="customer-1",\n        amount=-350,\n        tx_type="payment",\n        order_no="ORDER-1",\n        order_channel_id="ticket-1",\n        db_file=db_file,\n    )\n    second = adjust_wallet_balance(\n        customer_id="customer-1",\n        amount=-350,\n        tx_type="payment",\n        order_no="ORDER-1",\n        order_channel_id="ticket-1",\n        db_file=db_file,\n    )\n\n    assert first["id"] == second["id"]\n    assert get_wallet_balance("customer-1", db_file) == 1650\n    rows = get_wallet_transactions("customer-1", limit=10, db_file=db_file)\n    assert [row["type"] for row in rows] == ["payment", "topup"]\n    assert rows[0]["order_no"] == "ORDER-1"\n\n    with pytest.raises(ValueError, match="金額不同"):\n        adjust_wallet_balance(\n            customer_id="customer-1",\n            amount=-351,\n            tx_type="payment",\n            order_no="ORDER-1",\n            db_file=db_file,\n        )\n\n\ndef test_wallet_rejects_overdraft_with_customer_facing_amounts(tmp_path):\n    db_file = tmp_path / "bot.db"\n    with pytest.raises(ValueError) as exc_info:\n        adjust_wallet_balance(\n            customer_id="customer-2",\n            amount=-500,\n            tx_type="payment",\n            order_no="ORDER-2",\n            db_file=db_file,\n        )\n\n    message = str(exc_info.value)\n    assert "目前餘額 0T" in message\n    assert "無法扣除 500T" in message\n''', encoding="utf-8")


def update_architecture_doc() -> None:
    path = ROOT / "ARCHITECTURE.md"
    text = path.read_text(encoding="utf-8")
    note = "\n- Wallet persistence is canonical in `services/wallet_service.py`; Discord/Web layers may adapt identities or presentation, but must not open or mutate wallet tables directly.\n"
    if "Wallet persistence is canonical" not in text:
        text = text.rstrip() + "\n" + note
        path.write_text(text, encoding="utf-8")


def main() -> None:
    update_wallet_service()
    update_bot()
    update_budget()
    write_test()
    update_architecture_doc()
    # One-shot tooling must not ship to production.
    (ROOT / ".github" / "workflows" / "phase8-wallet-canonicalize.yml").unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
