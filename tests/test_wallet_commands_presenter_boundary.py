from __future__ import annotations

from pathlib import Path

from services.wallet_discord_presenter import wallet_transaction_type_label


ROOT = Path(__file__).resolve().parents[1]


def test_wallet_commands_delegate_presentation() -> None:
    source = (ROOT / "cogs/wallet_commands.py").read_text(encoding="utf-8")

    assert "from services.wallet_discord_presenter import" in source
    assert "def build_wallet_history_embed" not in source
    assert "get_wallet_transactions(" not in source
    assert "build_member_info_embed(" not in source
    assert "format_customer_notes_for_staff(" not in source


def test_presenter_uses_canonical_wallet_service() -> None:
    source = (ROOT / "services/wallet_discord_presenter.py").read_text(
        encoding="utf-8"
    )

    assert "from services.wallet_service import" in source
    assert "sqlite3" not in source


def test_wallet_transaction_type_labels() -> None:
    assert wallet_transaction_type_label("topup") == "儲值"
    assert wallet_transaction_type_label("tip_payment") == "雞腿扣款"
    assert wallet_transaction_type_label("custom") == "custom"
