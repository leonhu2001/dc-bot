from views.panels import MainPanelView, build_main_panel_embed


def test_main_service_panel_embed_copy():
    embed = build_main_panel_embed()

    assert embed.title == "魔丸娛樂｜聯絡客服"
    assert "🔔 呼叫客服" in (embed.description or "")
    assert "私人客服票口" in (embed.description or "")
    assert "AM 10:00－隔日 AM 2:00" in (embed.description or "")


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
