from views.panels import MainPanelView, build_main_panel_embed


def test_main_service_panel_embed_copy():
    embed = build_main_panel_embed()

    assert embed.title == "魔丸娛樂｜聯絡客服"
    assert "🔔 呼叫客服" in (embed.description or "")
    assert "私人客服票口" in (embed.description or "")
    assert "AM 10:00－隔日 AM 2:00" in (embed.description or "")
    assert len(embed.description or "") < 4096  # Discord Embed.description limit


def test_main_service_panel_has_all_six_clickable_channel_mentions_in_order():
    embed = build_main_panel_embed()
    description = embed.description or ""

    channels = (
        ("價目表", "1569412217269395597"),
        ("下單須知", "1543738337519730768"),
        ("三角洲", "1562940108246753331"),
        ("特戰英豪", "1562940127976890509"),
        ("英雄聯盟", "1562940161313087498"),
        ("Steam", "1562940249171042415"),
        ("APEX", "1562940146632888450"),
    )
    previous_index = -1
    for label, channel_id in channels:
        mention = f"<#{channel_id}>"
        assert label in description
        assert description.count(mention) == 1
        assert description.index(mention) > previous_index
        previous_index = description.index(mention)

    assert "私人客服票口" in description
    assert "🔔 呼叫客服" in description
    assert "客服服務時間" in description


def test_main_service_panel_order_links_have_no_decorative_emojis():
    text = build_main_panel_embed().description or ""
    assert "📌 **下單前先看看**" in text
    assert "**各遊戲下單區**" in text
    for name in ("價目表", "下單須知", "三角洲", "特戰英豪", "英雄聯盟", "Steam 遊戲", "APEX"):
        assert f"{name}：<#" in text
        line = next(line for line in text.splitlines() if line.startswith(f"{name}：<#"))
        assert line.startswith(name)
    for unwanted in ("📖 價目表：", "🎮 **各遊戲下單區**", "🔺 三角洲：",
                     "🎯 特戰英豪：", "⚔️ 英雄聯盟：", "🕹️ Steam 遊戲：", "🏹 APEX："):
        assert unwanted not in text


def test_main_service_panel_existing_message_is_edited_on_bot_startup():
    from pathlib import Path

    bot_source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(
        encoding="utf-8"
    )
    assert "MAIN_SERVICE_PANEL_MESSAGE_ID = 1537533276884045856" in bot_source
    assert "message = await channel.fetch_message(" in bot_source
    assert "MAIN_SERVICE_PANEL_MESSAGE_ID\n" in bot_source
    assert "embed=build_main_panel_embed()," in bot_source
    assert "view=MainPanelView()," in bot_source
    assert "if await refresh_main_service_panel():" in bot_source


def test_main_service_panel_buttons_have_clear_icons():
    view = MainPanelView()
    buttons = {
        item.label: str(item.emoji)
        for item in view.children
        if getattr(item, "label", None)
    }

    assert buttons == {
        "呼叫客服": "🔔",
        "我要入職": "💼",
        "我要客訴": "⚠️",
        "顧客意見": "💬",
    }
