from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")
COG = (ROOT / "cogs" / "reward_redeem_commands.py").read_text(encoding="utf-8")


def test_reward_redeem_commands_live_in_cog():
    assert 'name="reward_redeem_panel"' in COG
    assert "class RewardRedeemView" in COG
    assert "class RewardRedeemSelect" in COG
    assert "POINT_REDEEM_ITEMS =" in COG
    assert '"free_play_1h"' in COG
    assert "import bot" not in COG
    assert "from bot import" not in COG


def test_bot_only_keeps_reward_redeem_boundary_dependencies():
    assert "async def reward_redeem_panel" not in BOT
    assert "class RewardRedeemView" not in BOT
    assert "class RewardRedeemSelect" not in BOT
    assert "from cogs.reward_redeem_commands import (" in BOT
    assert '"cogs.reward_redeem_commands"' in BOT
    assert "bot.add_view(RewardRedeemView())" in BOT
    assert "point_redeem_items=POINT_REDEEM_ITEMS" in BOT
    assert "point_redeem_items_by_key=POINT_REDEEM_ITEMS_BY_KEY" in BOT
