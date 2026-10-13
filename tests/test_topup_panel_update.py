from pathlib import Path


def test_topup_panel_command_can_edit_existing_message():
    source = (
        Path(__file__).resolve().parents[1]
        / "cogs"
        / "setup_commands.py"
    ).read_text(encoding="utf-8")

    assert "description=\"建立或更新魔丸娛樂儲值中心面板\"" in source
    assert "message_id: str | None = None" in source
    assert "fetch_message(target_message_id)" in source
    assert "await target_message.edit(embed=embed, view=view)" in source
    assert "target_message.author.id != bot_user.id" in source


def test_topup_panel_update_is_not_hardcoded_to_one_message():
    source = (
        Path(__file__).resolve().parents[1]
        / "cogs"
        / "setup_commands.py"
    ).read_text(encoding="utf-8")

    assert "1545150477195411540" not in source
    assert "要原地更新的 Panel 訊息 ID" in source
