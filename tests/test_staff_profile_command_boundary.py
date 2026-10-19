from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")
COG = (ROOT / "cogs" / "staff_profile_commands.py").read_text(encoding="utf-8")

EXPECTED_COMMANDS = {
    "my_favorites",
    "browse_staff_profiles",
    "staff_profile_panel",
    "refresh_staff_profile_panel",
}


def test_staff_profile_slash_commands_are_owned_by_cog() -> None:
    for command_name in EXPECTED_COMMANDS:
        marker = f'name="{command_name}"'
        assert marker in COG
        assert marker not in BOT

    assert '"cogs.staff_profile_commands"' in BOT
    assert "import bot" not in COG
    assert "from bot import" not in COG


def test_staff_profile_cog_exposes_expected_app_commands() -> None:
    module = importlib.import_module("cogs.staff_profile_commands")
    command_names = {
        command.name
        for command in module.StaffProfileCommands.__cog_app_commands__
    }
    assert EXPECTED_COMMANDS <= command_names


def test_unrelated_order_repair_and_persistent_profile_restore_stay_in_bot() -> None:
    assert 'name="fix_acceptance_payment_panel"' in BOT
    assert "get_staff_profile_panel_rows()" in BOT
    assert "bot.add_view(StaffProfilePanelView(staff_id)" in BOT
