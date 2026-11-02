from __future__ import annotations

from pathlib import Path

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
    assert "累積 **10 小時** → 贈送 **1 小時券**" in entertainment

    assert "520T / H" in sweet
    assert "1314T / H" in sweet
    assert "500T / H" in teaching

    for text in (entertainment, sweet, teaching):
        assert "+100T" in text
        assert "2H 或 2局以上免指定費" in text


def test_delta_price_list_button_routes_to_selector_without_changing_other_games() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    delta_channel = int(quick.QUICK_ORDER_V2_CHANNELS["delta"])

    assert price_lists.has_price_list(delta_channel)
    assert "DeltaPriceListCategorySelect" in source
    assert "DeltaMobilePriceListSelect" in source
    assert 'custom_id="quick_order_v2_delta_price_list_category"' in source
    assert 'custom_id="quick_order_v2_delta_mobile_price_list"' in source
    assert "_valorant_price_list(interaction)" in source
    assert "_lol_price_list(interaction)" in source
    assert "_apex_price_list(interaction)" in source
    assert "_steam_price_list(interaction)" in source
