from __future__ import annotations

from pathlib import Path

from cogs.wallet_commands import WalletCommands


ROOT = Path(__file__).resolve().parents[1]
WALLET_COMMAND_NAMES = {
    "wallet_add",
    "wallet_adjust",
    "wallet_refund",
    "wallet_history",
    "my_wallet_history",
    "wallet_refund_order",
    "my_info",
}


def test_bot_entrypoint_loads_wallet_command_cog_without_owning_commands() -> None:
    source = (ROOT / "bot.py").read_text(encoding="utf-8")

    assert '"cogs.wallet_commands"' in source
    assert "def build_customer_info_with_wallet_embed(" not in source
    assert "def build_wallet_history_embed(" not in source
    assert "def wallet_transaction_type_label(" not in source

    for command_name in WALLET_COMMAND_NAMES:
        assert f'name="{command_name}"' not in source


def test_wallet_cog_preserves_command_surface_and_guild_registration() -> None:
    source = (ROOT / "cogs/wallet_commands.py").read_text(encoding="utf-8")
    command_names = {
        command.name
        for command in WalletCommands.__cog_app_commands__
    }

    assert command_names == WALLET_COMMAND_NAMES
    assert "bot.tree.copy_global_to" in source
    assert "guild_id_value" in source
    assert "import bot" not in source
    assert "from bot import" not in source
