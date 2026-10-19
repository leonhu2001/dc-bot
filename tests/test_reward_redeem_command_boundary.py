from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")
COG = (ROOT / "cogs" / "reward_redeem_commands.py").read_text(encoding="utf-8")
CATALOG = (ROOT / "services" / "point_benefit_catalog.py").read_text(encoding="utf-8")


def test_standalone_reward_redeem_command_is_retired():
    assert 'name="reward_redeem_panel"' not in COG
    assert "async def reward_redeem_panel" not in COG
    assert "save_bot_data" not in COG
    assert "point_adjustment" not in COG
    assert "POINT_REDEEM_ITEMS = [" not in COG
    assert "from services.point_benefit_catalog import" in COG
    assert "點數福利已整合到自助下單流程" in COG


def test_legacy_reward_panel_fails_closed_with_same_custom_ids():
    assert "class RewardRedeemView" in COG
    assert 'custom_id="reward_redeem_select"' in COG
    assert 'custom_id="reward_redeem_confirm_button"' in COG
    assert "LegacyRewardRedeemSelect" in COG


def test_bot_keeps_only_legacy_view_and_canonical_catalog_boundary():
    assert "async def reward_redeem_panel" not in BOT
    assert "class RewardRedeemView" not in BOT
    assert "from cogs.reward_redeem_commands import (" in BOT
    assert '"cogs.reward_redeem_commands"' in BOT
    assert "bot.add_view(RewardRedeemView())" in BOT
    assert "point_redeem_items=POINT_REDEEM_ITEMS" in BOT
    assert "point_redeem_items_by_key=POINT_REDEEM_ITEMS_BY_KEY" in BOT
    assert "Canonical point redemption catalog used by both Discord self-service and web checkout." in CATALOG
