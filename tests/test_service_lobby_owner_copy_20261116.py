from __future__ import annotations

import ast
from pathlib import Path
import re

from services.quick_order_v2 import QUICK_ORDER_V2_CHANNELS
from scripts.apply_main_service_panel_once import (
    EXPECTED_BUTTON_IDS,
    _button_pairs,
    _components_match,
    _existing_button_styles_match,
    _price_list_id,
)
from views.panels import (
    MainPanelView,
    SERVICE_LOBBY_GAME_CHANNELS,
    SERVICE_LOBBY_ORDER_NOTICE_CHANNEL_ID,
    build_main_panel_embed,
)


ROOT = Path(__file__).resolve().parents[1]


def test_service_lobby_copy_has_approved_navigation_and_notice():
    embed = build_main_panel_embed(price_list_channel_id=1234567890)
    text = str(embed.description)
    assert embed.title == "魔丸娛樂｜聯絡客服"
    assert text.startswith("歡迎來到魔丸娛樂！\n")
    assert "📌 **下單前先看**" in text
    assert "🎮 **各遊戲下單區**" in text
    assert "價目表：<#1234567890>" in text
    assert (
        f"下單須知：<#{SERVICE_LOBBY_ORDER_NOTICE_CHANNEL_ID}>"
        in text
    )
    assert SERVICE_LOBBY_ORDER_NOTICE_CHANNEL_ID == 1543738337519730768

    expected = (
        ("三角洲", QUICK_ORDER_V2_CHANNELS["delta"]),
        ("特戰英豪", QUICK_ORDER_V2_CHANNELS["valorant"]),
        ("英雄聯盟", QUICK_ORDER_V2_CHANNELS["lol"]),
        ("Steam 遊戲", QUICK_ORDER_V2_CHANNELS["steam"]),
        ("APEX", QUICK_ORDER_V2_CHANNELS["apex"]),
    )
    assert SERVICE_LOBBY_GAME_CHANNELS == expected
    for name, channel_id in expected:
        assert f"{name}：<#{channel_id}>" in text
    assert text.index("三角洲：") < text.index("特戰英豪：")
    assert text.index("特戰英豪：") < text.index("英雄聯盟：")
    assert text.index("英雄聯盟：") < text.index("Steam 遊戲：")
    assert text.index("Steam 遊戲：") < text.index("APEX：")
    assert "**需要真人客服協助嗎？**" in text
    assert "私人客服票口並通知客服" in text
    assert "AM 10:00－隔日 AM 2:00" in text


def test_service_lobby_uses_only_owner_approved_pin_and_gamepad_emoji():
    embed = build_main_panel_embed()
    view = MainPanelView()
    content = str(embed.title) + str(embed.description)
    assert content.count("📌") == 1
    assert content.count("🎮") == 1
    stripped = content.replace("📌", "").replace("🎮", "")
    other_symbols = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", stripped)
    assert other_symbols == []
    assert all(button.emoji is None for button in view.children)
    assert [button.label for button in view.children] == [
        "呼叫客服", "我要入職", "我要客訴", "顧客意見",
    ]
    assert tuple(button.custom_id for button in view.children) == EXPECTED_BUTTON_IDS
    assert len(view.to_components()) == 1


def test_safe_one_time_service_panel_update_never_loses_buttons():
    original = MainPanelView().to_components()
    assert len(_button_pairs(original)) == 4
    with_api_ids = [{
        **original[0],
        "id": 0,
        "components": [{**button, "id": index + 1}
                       for index, button in enumerate(original[0]["components"])],
    }]
    assert _components_match(with_api_ids, original)
    assert _existing_button_styles_match(with_api_ids, original)

    old_emoji = [{
        **original[0],
        "components": [
            {**button, "emoji": {"name": "🔔"}} if index == 0 else button
            for index, button in enumerate(original[0]["components"])
        ],
    }]
    assert not _components_match(old_emoji, original)
    assert _existing_button_styles_match(old_emoji, original)

    changed = [{
        **original[0],
        "components": [
            {**button, "label": "變更"} if index == 0 else button
            for index, button in enumerate(original[0]["components"])
        ],
    }]
    assert not _existing_button_styles_match(changed, original)


def test_price_list_link_is_exactly_the_approved_owner_discord_url():
    from views.panels import SERVICE_LOBBY_PRICE_LIST_CHANNEL_ID

    approved = 1569412217269395597
    guild_id = 1129474191226306672
    assert SERVICE_LOBBY_PRICE_LIST_CHANNEL_ID == approved
    assert (
        f"https://discord.com/channels/{guild_id}/{approved}"
        == "https://discord.com/channels/1129474191226306672/1569412217269395597"
    )
    assert _price_list_id(specified=None) == approved
    assert _price_list_id(specified=approved) == approved
    assert f"價目表：<#{approved}>" in build_main_panel_embed().description

    import pytest
    with pytest.raises(RuntimeError, match="與店主核准的"):
        _price_list_id(specified=999)


def test_one_time_updater_does_not_enumerate_non_thread_guild_channels():
    source = (ROOT / "scripts/apply_main_service_panel_once.py").read_text(
        encoding="utf-8"
    )
    assert '"/guilds/{guild_id}/channels"' not in source
    assert 'client, "GET", f"/guilds/{guild_id}/channels"' not in source
    assert "price_id = _price_list_id(specified=args.price_list_channel_id)" in source
    assert "if not args.apply:" in source


def test_manual_update_not_called_by_bot_startup_or_implicit_script_import():
    bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
    function = bot_source.split("async def refresh_main_service_panel()", 1)[1]
    function = function.split("# ========= Bot 事件 =========", 1)[0]
    tree = ast.parse("async def fn():" + function.split(":", 1)[1])
    calls = [
        ast.unparse(node.func) for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    assert "message.edit" not in calls
    assert "channel.send" not in calls

    script = (ROOT / "scripts/apply_main_service_panel_once.py").read_text(
        encoding="utf-8"
    )
    assert 'if __name__ == "__main__":' in script
    assert "if not args.apply:" in script
    assert '"PATCH"' in script
    assert "_write_backup(current, message_id)" in script
