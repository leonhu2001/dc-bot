from views.panels import build_main_panel_embed


def test_main_service_panel_embed_copy():
    embed = build_main_panel_embed()

    assert embed.title == "魔丸娛樂｜服務大廳"
    assert "點單、入職、客訴與顧客意見皆可由此進入。" in (embed.description or "")
    assert "AM 10:00－隔日 AM 2:00" in (embed.description or "")
