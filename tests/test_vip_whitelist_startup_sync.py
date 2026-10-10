from pathlib import Path

from views.voice import build_vip_whitelist_overwrite


def test_vip_whitelist_can_use_video_stream():
    assert build_vip_whitelist_overwrite().stream is True


def test_bot_ready_runs_existing_vip_room_permission_sweep():
    text = Path("bot.py").read_text(encoding="utf-8")
    assert "sync_all_existing_vip_whitelist_permissions" in text
    assert "VIP_POLICY_STARTUP_SYNC_V1" in text
