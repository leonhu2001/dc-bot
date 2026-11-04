from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services import quick_order_v2 as quick
from services import quick_order_v2_price_lists as price_lists


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services" / "quick_order_v2_price_lists.py"


def test_delta_price_list_keeps_four_top_level_categories() -> None:
    assert [item[0] for item in price_lists.DELTA_PRICE_LIST_CATEGORIES] == [
        "desktop",
        "mobile",
        "farm",
        "fun",
    ]
    assert [item[1] for item in price_lists.DELTA_PRICE_LIST_CATEGORIES] == [
        "端遊",
        "手遊",
        "代肝代解",
        "趣味單",
    ]



def test_delta_desktop_price_list_has_nine_requested_order_types() -> None:
    labels = [str(plan["label"]) for plan in price_lists.DELTA_DESKTOP_PRICE_LISTS.values()]
    assert labels == [
        "娛樂陪",
        "一陪一護",
        "黑潮爆破",
        "甜蜜單",
        "體驗單",
        "技術陪",
        "教學單",
        "油鍋單",
        "賭約單",
    ]


def test_delta_desktop_price_list_prices_and_rules_match_approved_copy() -> None:
    plans = price_lists.DELTA_DESKTOP_PRICE_LISTS
    expected = {
        "entertainment": ("320T / H", "600T / H", "10 小時", "1 小時券", "+100T", "不保撤"),
        "one_guard": ("720T / H", "770T / H", "8 殺", "6 殺", "+100T"),
        "black_tide": ("320T / H", "300T / H", "400T / H", "380T / H", "30 分鐘券"),
        "sweet": ("520T / H", "1314T / H", "專屬暱稱", "管理層", "+100T"),
        "trial": ("450T", "777W", "900T", "1688W", "金級以上", "打手選圖"),
        "technical": ("400T / H", "750T / H", "450T / H", "850T / H", "1000T / H", "666W", "800W", "500W + 2 沙保", "4 沙保", "+100T"),
        "teaching": ("500T / H", "3H 起標", "地圖理解", "復盤"),
        "oil": ("2600T", "2000W", "1800T", "1500W", "4000T", "3500W", "航天基地", "撞場"),
        "bet": ("800T", "800W", "1200T", "1000W", "1500T", "1200W", "打手選圖"),
    }
    assert set(plans) == set(expected)
    for key, terms in expected.items():
        text = str(plans[key]["text"])
        assert "抱歉" not in text
        assert "｜" not in text
        assert "```text" in text
        for term in terms:
            assert term in text, (key, term)


def test_delta_desktop_selector_uses_existing_two_level_private_view() -> None:
    view = price_lists.DeltaPriceListView(category="desktop", desktop_plan="technical")
    assert len(view.children) == 2
    assert isinstance(view.children[0], price_lists.DeltaPriceListCategorySelect)
    select = view.children[1]
    assert isinstance(select, price_lists.DeltaDesktopPriceListSelect)
    assert select.custom_id == "quick_order_v2_delta_desktop_price_list"
    assert [option.label for option in select.options] == [
        str(plan["label"]) for plan in price_lists.DELTA_DESKTOP_PRICE_LISTS.values()
    ]
    assert [option.value for option in select.options if option.default] == ["technical"]

def test_other_games_use_service_dropdown_without_legacy_dividers() -> None:
    interaction = SimpleNamespace(guild=None)
    for game in ("valorant", "lol", "apex", "steam"):
        channel_id = int(quick.QUICK_ORDER_V2_CHANNELS[game])
        expected_labels = (
            ["娛樂陪", "甜蜜單"]
            if game == "steam"
            else ["娛樂陪", "技術陪", "甜蜜單", "教學單"]
        )
        view = price_lists.GamePriceListView(channel_id)
        assert len(view.children) == 1
        select = view.children[0]
        assert isinstance(select, price_lists.GamePriceListSelect)
        assert select.custom_id == f"quick_order_v2_game_price_list_{channel_id}"
        assert [option.label for option in select.options] == expected_labels
        assert view.timeout == 840

        root = price_lists._game_root_embed(channel_id)
        assert "請選擇" in root.description
        assert "━━━━━━━━" not in root.description

        plans = price_lists._game_price_list_sections(interaction, channel_id)
        assert list(plans) == [option.value for option in select.options]
        assert all("━━━━━━━━" not in text for text in plans.values())
        assert all("｜" not in text for text in plans.values())
        assert all("廠商" not in text for text in plans.values())
        for key, contents in plans.items():
            embed = price_lists._game_plan_embed(interaction, channel_id, key)
            assert embed.description == contents
            assert key in dict(price_lists._game_price_list_options(channel_id))
            assert 0 < len(embed.description) <= 4096


def test_game_price_list_preserves_category_prices_and_rules() -> None:
    interaction = SimpleNamespace(guild=None)
    game_data = (
        ("valorant", ("超凡陪", "神話陪", "輻能陪"), ("330T", "350T", "380T", "370T")),
        ("lol", ("大師陪", "宗師陪", "菁英陪"), ("340T", "360T", "400T")),
        ("apex", ("鑽石陪", "大師陪", "頂獵陪"), ("400T", "480T", "580T", "630T")),
    )
    for game, ranks, tech_prices in game_data:
        channel_id = int(quick.QUICK_ORDER_V2_CHANNELS[game])
        plans = price_lists._game_price_list_sections(interaction, channel_id)
        entertainment = plans["entertainment"]
        technical = plans["technical"]
        sweet = plans["sweet"]
        teaching = plans["teaching"]
        assert "娛樂陪" in entertainment
        assert "娛樂陪累積回饋" in entertainment
        assert "指定陪玩" in entertainment and "+100T" in entertainment
        assert "娛樂陪累積回饋" not in technical
        for rank in ranks:
            assert rank in technical
            assert rank not in entertainment
        for amount in tech_prices:
            assert amount in technical
        assert "指定陪玩" in technical and "+100T" in technical
        assert "520T / H" in sweet and "1314T / H" in sweet
        assert "指定陪玩" in sweet and "2H 以上免指定費" in sweet
        assert "500T / H" in teaching and "3H 起標" in teaching
        for other_key in ("entertainment", "technical", "sweet"):
            assert "500T / H" not in plans[other_key]

    steam_id = int(quick.QUICK_ORDER_V2_CHANNELS["steam"])
    steam = price_lists._game_price_list_sections(interaction, steam_id)
    assert tuple(steam) == ("entertainment", "sweet")
    assert "一般陪玩" in steam["entertainment"]
    assert "320T / H" in steam["entertainment"]
    assert "520T / H" in steam["sweet"]
    assert "1314T / H" in steam["sweet"]
    assert all("教學單" not in p for p in steam.values())


def test_game_price_list_keeps_selected_option_checked() -> None:
    for game in ("valorant", "lol", "apex"):
        channel_id = int(quick.QUICK_ORDER_V2_CHANNELS[game])
        view = price_lists.GamePriceListView(channel_id, selected="technical")
        assert [opt.value for opt in view.children[0].options if opt.default] == ["technical"]



def test_shared_special_offers_follow_existing_game_price_lists() -> None:
    interaction = SimpleNamespace(guild=None)
    for price_list, teacher in (
        (price_lists._valorant_price_list(interaction), "輻能導師"),
        (price_lists._lol_price_list(interaction), "菁英導師"),
        (price_lists._apex_price_list(interaction), "頂獵導師"),
    ):
        assert price_list.index("📌 **指定陪玩**") < price_list.index("💗 **甜蜜單**")
        assert price_list.index("💗 **甜蜜單**") < price_list.index("📚 **教學單（1 對 1）**")
        for value in ("520T / H", "1314T / H", "500T / H", "3H 起標", teacher):
            assert value in price_list
        assert len(price_list) <= 4096

    steam = price_lists._steam_price_list(interaction)
    assert steam.index("📌 **指定陪玩**") < steam.index("💗 **甜蜜單**")
    assert steam.index("💗 **甜蜜單**") < steam.index("📚 **教學單**")
    assert "520T / H" in steam and "1314T / H" in steam
    assert "尚未開放自助下單" in steam
    assert "500T / H" not in steam
    assert len(steam) <= 4096


def test_public_price_list_acks_before_loading_content() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    callback = source.split("class QuickPriceListButton(", 1)[1]
    assert "await interaction.response.defer(ephemeral=True, thinking=True)" in callback
    assert "await interaction.edit_original_response(" in callback
    assert callback.index("await interaction.response.defer(") < callback.index("_game_root_embed(")
    assert "view=GamePriceListView(self.source_channel_id)" in callback


def test_delta_mobile_price_list_has_only_approved_seven_order_types() -> None:
    labels = [
        str(plan["label"])
        for plan in price_lists.DELTA_MOBILE_PRICE_LISTS.values()
    ]
    assert labels == [
        "體驗單",
        "保底單",
        "大紅單",
        "絕巴保底單",
        "娛樂陪",
        "甜蜜單",
        "教學單",
    ]
    assert "技術陪" not in labels
    assert "一陪一護" not in labels


def test_delta_mobile_price_list_uses_aligned_blocks_without_vertical_separators() -> None:
    for plan in price_lists.DELTA_MOBILE_PRICE_LISTS.values():
        text = str(plan["text"])
        assert "```text" in text
        assert "｜" not in text


def test_delta_mobile_fixed_result_prices_match_approved_copy() -> None:
    trial = str(price_lists.DELTA_MOBILE_PRICE_LISTS["trial"]["text"])
    guarantee = str(price_lists.DELTA_MOBILE_PRICE_LISTS["guarantee"]["text"])
    big_red = str(price_lists.DELTA_MOBILE_PRICE_LISTS["big_red"]["text"])
    babel = str(price_lists.DELTA_MOBILE_PRICE_LISTS["babel"]["text"])

    assert "777W" in trial and "400T" in trial
    assert "1688W" in trial and "800T" in trial

    for amount, price in (
        ("1500W", "600T"),
        ("4200W", "2000T"),
        ("110M", "4000T"),
        ("300M", "10000T"),
    ):
        assert amount in guarantee and price in guarantee

    for count, price in (("1 大紅", "1000T"), ("5 大紅", "4000T"), ("10 大紅", "7000T")):
        assert count in big_red and price in big_red
    assert "100萬以上" in big_red

    for price in ("600T", "3000T", "5000T"):
        assert price in babel
    assert "2 個沙色保險 ＋ 800W 保底" in babel
    assert "累積 10 個沙色保險 ＋ 6000W 保底" in babel
    assert "累積 20 個沙色保險 ＋ 100M 保底" in babel
    assert "不出不結單" in babel


def test_delta_mobile_fixed_result_orders_do_not_show_specify_fee() -> None:
    for key in ("trial", "guarantee", "big_red", "babel"):
        text = str(price_lists.DELTA_MOBILE_PRICE_LISTS[key]["text"])
        assert "指定陪玩" not in text
        assert "+100T" not in text
        assert "免指定費" not in text


def test_delta_mobile_timed_orders_show_specify_fee_and_coupon_policy() -> None:
    entertainment = str(price_lists.DELTA_MOBILE_PRICE_LISTS["entertainment"]["text"])
    sweet = str(price_lists.DELTA_MOBILE_PRICE_LISTS["sweet"]["text"])
    teaching = str(price_lists.DELTA_MOBILE_PRICE_LISTS["teaching"]["text"])

    assert "320T / H" in entertainment
    assert "600T / H" in entertainment
    assert "計時" in entertainment
    assert "累積 10 小時 → 贈送 1 小時券" in entertainment

    assert "520T / H" in sweet
    assert "1314T / H" in sweet
    assert "500T / H" in teaching

    for text in (entertainment, sweet, teaching):
        assert "+100T" in text
        assert "2H 或 2局以上免指定費" in text


def test_apex_entertainment_loyalty_row_is_framed_like_other_price_rows() -> None:
    text = price_lists._apex_price_list(SimpleNamespace(guild=None))
    loyalty_heading = "🎁 **娛樂陪累積回饋**"
    assert loyalty_heading in text
    loyalty_section = text.split(loyalty_heading, 1)[1].split("📌 **指定陪玩**", 1)[0]
    assert "```text" in loyalty_section
    assert "計時" in loyalty_section
    assert "累積 10 小時 → 贈送 1 小時券" in loyalty_section


def test_delta_price_list_button_routes_to_selector_without_changing_other_games() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    delta_channel = int(quick.QUICK_ORDER_V2_CHANNELS["delta"])

    assert price_lists.has_price_list(delta_channel)
    assert "DeltaPriceListCategorySelect" in source
    assert "DeltaDesktopPriceListSelect" in source
    assert 'custom_id="quick_order_v2_delta_desktop_price_list"' in source
    assert "DeltaMobilePriceListSelect" in source
    assert 'custom_id="quick_order_v2_delta_price_list_category"' in source
    assert 'custom_id="quick_order_v2_delta_mobile_price_list"' in source
    assert "_valorant_price_list(interaction)" in source
    assert "_lol_price_list(interaction)" in source
    assert "_apex_price_list(interaction)" in source
    assert "_steam_price_list(interaction)" in source
