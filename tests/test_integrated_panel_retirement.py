from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "cogs" / "setup_commands.py").read_text(encoding="utf-8")


def _command_block(name: str, next_name: str) -> str:
    start = SETUP.index(f'name="{name}"')
    end = SETUP.index(f'name="{next_name}"', start)
    return SETUP[start:end]


def test_complaint_panel_alias_does_not_create_a_second_panel():
    block = _command_block("complaint_panel", "feedback_panel")
    assert "已整合到「/setup panel」" in block
    assert "interaction.channel.send" not in block
    assert "ComplaintPanelView" not in block


def test_feedback_panel_alias_does_not_create_a_second_panel():
    block = _command_block("feedback_panel", "play_voice")
    assert "已整合到「/setup panel」" in block
    assert "interaction.channel.send" not in block
    assert "FeedbackPanelView" not in block
