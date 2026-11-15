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
        "吃到發胖",
        "我們的愛",
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
    assert rule.catalog_group_label == ""

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
        "吃到發胖",
        "我們的愛",
        "豪到你了嗎",
        "比翼雙飛",
    ]


def test_one_life_clear_is_code_owned_even_with_stale_admin_override(monkeypatch) -> None:
    from services import orders
    from services.order_rules import get_base_rule

    key = "fun_eat_yourself"
    base = get_base_rule(key)
    assert (base.label, base.price, base.catalog_group_label) == (
        "一命通關", 13888, ""
    )
    monkeypatch.setattr(order_rules.ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(order_rules.ORDER_RULES, "_override_cache", {
        key: {"payload": {
            "label": "想吃自己打",
            "price": 3000,
            "catalog_group_label": "想吃自己打",
            "allowed_roles": ["male_companion"],
        }}
    })
    assert order_rules.ORDER_RULES[key] == base
    assert orders.ORDER_RULE_KEY_BY_LABEL["想吃自己打"] == key
    assert orders.ORDER_RULE_KEY_BY_LABEL["一命通關"] == key
    assert [group["label"] for group in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]
            if any(item["rule_key"] == key for item in group["details"])] == ["一命通關"]
    assert [group["label"] for group in order_groups.get_grouped_order_catalog("delta_desktop_fun")
            if any(variant["rule_key"] == key for variant in group["variants"])] == ["一命通關"]


def test_old_read_no_reply_manager_override_cannot_duplicate_one_life_card(
    monkeypatch,
) -> None:
    from services import orders
    from services.order_rules import get_base_rule
    from web.app.services import order_catalog_cards

    # VPS used to show two 一命通關 13,888T cards: the second built-in fun
    # group read_no_reply could still be renamed through a stale manager
    # override even after one_life_clear was moved into the canonical source.
    monkeypatch.setattr(order_rules.ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(
        order_rules.ORDER_RULES,
        "_override_cache",
        {
            "fun_read_no_reply": {
                "payload": {
                    "label": "一命通關",
                    "price": 13888,
                    "catalog_group_label": "一命通關",
                }
            },
            "fun_eat_yourself": {
                "payload": {
                    "label": "想吃自己打",
                    "price": 3000,
                    "catalog_group_label": "想吃自己打",
                }
            },
        },
    )

    assert (get_base_rule("fun_read_no_reply").label, get_base_rule("fun_read_no_reply").price) == (
        "謹言慎行", 2500
    )
    assert (order_rules.ORDER_RULES["fun_read_no_reply"].label, order_rules.ORDER_RULES["fun_read_no_reply"].price) == (
        "謹言慎行", 2500
    )
    assert order_rules.ORDER_RULES["fun_eat_yourself"].label == "一命通關"
    assert order_rules.ORDER_RULES["fun_eat_yourself"].price == 13888

    cards = order_catalog_cards._build_cards("delta_desktop_fun")
    one_life = [card for card in cards if card["label"] == "一命通關"]
    careful_words = [card for card in cards if card["label"] == "謹言慎行"]
    assert len(one_life) == 1
    assert one_life[0]["key"] == "eat_yourself"
    assert one_life[0]["variant_count"] == 1
    assert one_life[0]["starting_price"] == 13888
    assert len(careful_words) == 1
    assert careful_words[0]["key"] == "read_no_reply"
    assert careful_words[0]["variant_count"] == 1
    assert careful_words[0]["starting_price"] == 2500

    assert order_catalog_cards._build_group_detail("read_no_reply")["variants"][0]["price"] == 2500
    assert order_catalog_cards._build_group_detail("eat_yourself")["variants"][0]["price"] == 13888
    assert orders.ORDER_RULE_KEY_BY_LABEL["已讀亂回"] == "fun_read_no_reply"
    assert orders.ORDER_RULE_KEY_BY_LABEL["想吃自己打"] == "fun_eat_yourself"


def test_fun_website_and_discord_catalog_match_current_price_card() -> None:
    from services import orders
    from web.app.services import order_catalog_cards

    site = {card["label"]: card for card in order_catalog_cards._build_cards("delta_desktop_fun")}
    # Production also has manager-created fun products (e.g. 俄羅斯輪盤),
    # which are intentionally absent from an empty CI fixture database.
    assert len(site) >= 5
    assert site["謹言慎行"]["starting_price"] == 2500
    assert site["一命通關"]["starting_price"] == 13888
    assert "已讀亂回" not in site

    discord_catalog = {
        group["label"]: group
        for group in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]
    }
    assert "謹言慎行" in discord_catalog
    assert "一命通關" in discord_catalog
    assert "已讀亂回" not in discord_catalog
    assert price_lists.DELTA_FUN_PRICE_LISTS["watch_your_words"]["label"] == "謹言慎行"
    assert "2500T" in price_lists.DELTA_FUN_PRICE_LISTS["watch_your_words"]["text"]


def test_source_owned_fun_rules_ignore_old_intro_override(monkeypatch) -> None:
    from web.app.services.order_groups import _presentation_intro
    from services import order_rule_store

    # A stale intro describing the five-extraction challenge must not appear
    # on 謹言慎行 even if the old admin row remains in audit history.
    monkeypatch.setattr(
        order_rule_store,
        "get_active_override",
        lambda rule_key: {"payload": {"intro": "五連撤才結單"}},
    )
    assert _presentation_intro("fun_read_no_reply") == ""
    assert _presentation_intro("fun_eat_yourself") == ""
