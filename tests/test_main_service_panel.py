from views.panels import MainPanelView, build_main_panel_embed


def test_main_service_panel_embed_copy():
    embed = build_main_panel_embed()
    description = embed.description or ""

    assert embed.title == "魔丸娛樂｜聯絡客服"
    assert "📌 **下單前先看**" in description
    assert "🎮 **各遊戲下單區**" in description
    assert "下單須知：<#1543738337519730768>" in description
    assert "請按下方 **呼叫客服**" in description
    assert "私人客服票口" in description
    assert "AM 10:00－隔日 AM 2:00" in description


def test_main_service_panel_buttons_have_no_unapproved_icons():
    view = MainPanelView()
    buttons = {
        item.label: item.emoji
        for item in view.children
        if getattr(item, "label", None)
    }
    assert buttons == {
        "呼叫客服": None,
        "我要入職": None,
        "我要客訴": None,
        "顧客意見": None,
    }
