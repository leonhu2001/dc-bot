from __future__ import annotations

from services import order_rules
from services import quick_order_v2_price_lists as price_lists
from web.app.services import order_groups


def test_delta_fun_price_list_has_owner_approved_items() -> None:
    labels = [str(plan["label"]) for plan in price_lists.DELTA_FUN_PRICE_LISTS.values()]
    assert labels == [
        "俄羅斯輪盤",
        "戀與三角洲",
        "謹言慎行",
        "一命通關",
        "豪到你了嗎",
        "比翼雙飛",
    ]


def test_delta_fun_russian_roulette_copy_and_image() -> None:
    plan = price_lists.DELTA_FUN_PRICE_LISTS["russian_roulette"]
    text = str(plan["text"])
    assert "1000T" in text
    assert "輪盤網站" in text
    assert "機器人自動記錄於票口" in text
    assert plan["image"] == "price_lists/delta_fun_russian_roulette.jpg"

    embed = price_lists._delta_fun_embed("russian_roulette")
    assert str(embed.image.url).startswith(
        "https://mowanentertainment.com/static/price_lists/delta_fun_russian_roulette.jpg?v="
    )


def test_delta_fun_love_delta_copy() -> None:
    text = str(price_lists.DELTA_FUN_PRICE_LISTS["love_delta"]["text"])
    for fragment in (
        "1688T",
        "2688T",
        "4688T",
        "6688T",
        "好感度達 **100** 結單",
        "金色物資／紫卡",
        "300W以上撤離",
        "好感度 **30**",
        "好感度 **60**",
    ):
        assert fragment in text
    assert "｜" not in text


def test_delta_fun_watch_your_words_copy() -> None:
    text = str(price_lists.DELTA_FUN_PRICE_LISTS["watch_your_words"]["text"])
    assert "2500T" in text
    assert "1888W" in text
    assert "3 個禁詞" in text
    assert "額外保底 **+50W**" in text
    assert "最多更換 **2 次**" in text


def test_delta_fun_one_life_clear_copy_rule_and_web_catalog() -> None:
    plan = price_lists.DELTA_FUN_PRICE_LISTS["eat_yourself"]
    text = str(plan["text"])
    assert plan["label"] == "一命通關"
    assert "13888T" in text
    assert "連續撤離 **5 把**" in text
    assert "每把帶出價值皆須達 **1000W**" in text
    assert "補場不會中斷既有連撤進度" in text
    assert "大紅可折抵 1 個場次" in text
    assert "想吃自己打" not in text

    rule = order_rules.ORDER_RULES["fun_eat_yourself"]
    assert rule.label == "一命通關"
    assert rule.price == 13888
    assert rule.catalog_group_label == "一命通關"

    current_specs = order_groups._current_group_specs()
    matching = [
        spec
        for spec in current_specs
        if any(key == "fun_eat_yourself" for key, _ in spec.get("variants", []))
    ]
    assert len(matching) == 1
    assert matching[0]["label"] == "一命通關"
    assert matching[0]["variants"] == [("fun_eat_yourself", "一命通關")]


def test_delta_fun_rich_enough_copy_and_image() -> None:
    plan = price_lists.DELTA_FUN_PRICE_LISTS["rich_enough"]
    text = str(plan["text"])
    assert "2000T" in text
    assert "1200W" in text
    assert "打手必須威龍" in text
    assert "必須防爆頭+老賽甲" in text
    assert "語音英文" in text
    assert "AS VAL、M7、M14" in text
    assert '打贏說 "豪到你了嗎，妹妹?"' in text
    assert '打輸說 "卡了"' in text
    assert '一個吸Four' in text
    assert '一個氣' in text
    assert '一個炮' in text
    assert '窩累同雷碗' in text
    assert '有感覺了嗎，妹妹' in text
    assert "保底 **+30W**" in text
    assert "請見下圖" not in text
    assert plan["image"] == "price_lists/delta_fun_hao_dao_ni_le_ma.jpg"

    embed = price_lists._delta_fun_embed("rich_enough")
    assert str(embed.image.url).startswith(
        "https://mowanentertainment.com/static/price_lists/delta_fun_hao_dao_ni_le_ma.jpg?v="
    )


def test_delta_fun_lovebirds_copy() -> None:
    text = str(price_lists.DELTA_FUN_PRICE_LISTS["lovebirds"]["text"])
    assert "2000T" in text
    assert "1314W" in text
    assert "愛稱" in text
    assert "保底 **+50W**" in text
    assert "必須開麥溝通" in text


def test_delta_fun_category_opens_second_level_selector() -> None:
    category_embed = price_lists._delta_category_embed("fun")
    assert category_embed.description == "請選擇要查看的單子。"

    view = price_lists.DeltaPriceListView(category="fun")
    assert any(
        isinstance(child, price_lists.DeltaFunPriceListSelect)
        for child in view.children
    )

    selector = next(
        child
        for child in view.children
        if isinstance(child, price_lists.DeltaFunPriceListSelect)
    )
    assert selector.custom_id == "quick_order_v2_delta_fun_price_list"
    assert [option.label for option in selector.options] == [
        "俄羅斯輪盤",
        "戀與三角洲",
        "謹言慎行",
        "一命通關",
        "豪到你了嗎",
        "比翼雙飛",
    ]
