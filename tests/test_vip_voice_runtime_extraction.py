from pathlib import Path


def test_vip_voice_lifecycle_is_owned_by_runtime_service():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    service = Path("services/vip_voice_runtime.py").read_text(encoding="utf-8")

    assert "def member_has_vip_voice_role" not in bot_source
    assert "async def delete_vip_voice_room_for_owner" not in bot_source
    assert "async def restore_persistent_vip_voice_rooms" not in bot_source
    assert "def member_has_vip_voice_role" in service
    assert "async def delete_vip_voice_room_for_owner" in service
    assert "async def restore_persistent_vip_voice_rooms" in service
    assert "def configure_vip_voice_runtime" in service
    assert "import bot" not in service
    assert "from bot import" not in service


def test_bot_keeps_discord_registration_and_binds_voice_runtime_explicitly():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    assert "@vip_group.command(" in bot_source
    assert "async def vip_create_voice" in bot_source
    assert "@bot.event" in bot_source
    assert "async def on_voice_state_update" in bot_source
    assert "configure_vip_voice_runtime(" in bot_source
    assert "set_vip_voice_hidden_user_ids(HIDDEN_VIP_USER_IDS)" in bot_source
