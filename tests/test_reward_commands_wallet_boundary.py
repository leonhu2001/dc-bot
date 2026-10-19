from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "reward_commands.py").read_text(encoding="utf-8")


def test_reward_commands_use_canonical_wallet_service():
    assert "from services.wallet_service import get_wallet_balance" in SOURCE
    assert "sqlite3" not in SOURCE
    assert "customer_wallets" not in SOURCE
    assert "wallet_transactions" not in SOURCE
    assert "CREATE TABLE" not in SOURCE


def test_member_info_still_includes_wallet_balance():
    assert 'name="錢包餘額"' in SOURCE
    assert "get_wallet_balance(customer_id)" in SOURCE
