from services.loyalty_benefits import loyalty_scope_key
from services.order_rules import ORDER_RULES
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.point_benefit_catalog import (
    LEGACY_POINT_REDEEM_ITEMS_BY_KEY,
    POINT_REDEEM_ITEMS,
    adapt_point_benefit_for_rule,
    calculate_one_seat_service_bonus_value,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)
from web.app.services.checkout_preview import (
    POINT_ITEMS as WEB_POINT_ITEMS,
    POINT_ITEM_MAP as WEB_POINT_ITEM_MAP,
    calculate_point_service_value,
    list_point_options,
)


def _catalog_costs():
    return {item["key"]: int(item["cost"]) for item in POINT_REDEEM_ITEMS}


def _group(category: str, label: str) -> dict:
    return next(
        group
        for group in SELF_SERVICE_ORDER_CATALOG[category]
        if str(group.get("label") or "") == label
    )


def test_point_catalog_supports_one_to_four_seat_service_rewards():
    assert _catalog_costs() == {
        "discount_50": 20,
        "free_specify_fee": 30,
        "discount_100": 45,
        "entertain_single_service_small": 80,
        "entertain_single_service_large": 140,
        "entertain_double_service_small": 160,
        "entertain_double_service_large": 280,
        "entertain_triple_service_small": 240,
        "entertain_triple_service_large": 420,
        "entertain_quad_service_small": 320,
        "entertain_quad_service_large": 560,
        "tech_single_service_small": 100,
        "tech_single_service_large": 180,
        "tech_double_service_small": 200,
        "tech_double_service_large": 360,
        "tech_triple_service_small": 300,
        "tech_triple_service_large": 540,
        "tech_quad_service_small": 400,
        "tech_quad_service_large": 720,
    }
    assert all("vip" not in item["key"].lower() for item in POINT_REDEEM_ITEMS)


def test_old_service_and_legacy_point_keys_are_lookup_only():
    selectable_keys = {item["key"] for item in POINT_REDEEM_ITEMS}
    for key in (
        "discount_20",
        "discount_30",
        "extra_hour_1h",
        "extra_game_2",
        "entertain_service_small",
        "entertain_service_large",
        "tech_service_small",
        "tech_service_large",
    ):
        assert key not in selectable_keys
        assert key in LEGACY_POINT_REDEEM_ITEMS_BY_KEY

    assert get_point_benefit_item("discount_20")["amount"] == 20
    assert get_point_benefit_item("extra_game_2")["games"] == 2
    assert get_point_benefit_item("entertain_service_large")["service_tier"] == "entertainment"


def test_entertainment_rewards_require_exact_one_to_four_seat_match():
    rules = {
        1: ORDER_RULES["basic_black_tide_entertain_1"],
        2: ORDER_RULES["basic_black_tide_entertain_2"],
        3: ORDER_RULES["basic_black_tide_entertain_3"],
        4: ORDER_RULES["basic_black_tide_entertain_4"],
    }
    benefits = {
        1: get_point_benefit_item("entertain_single_service_small"),
        2: get_point_benefit_item("entertain_double_service_small"),
        3: get_point_benefit_item("entertain_triple_service_small"),
        4: get_point_benefit_item("entertain_quad_service_small"),
    }

    for seat_count, rule in rules.items():
        for benefit_seats, benefit in benefits.items():
            assert is_service_bonus_allowed_for_rule(rule, benefit) is (
                seat_count == benefit_seats
            )

    hourly = adapt_point_benefit_for_rule(rules[4], benefits[4])
    assert hourly["kind"] == "extra_hours"
    assert hourly["hours"] == 0.5
    assert hourly["seat_count"] == 4
    assert "4陪" in hourly["name"]
    assert "4 位陪玩同步加贈" in hourly["summary"]


def test_player_count_products_match_voucher_seat_count_when_selection_is_known():
    rule = ORDER_RULES["valorant_entertain_ranked"]
    triple = get_point_benefit_item("entertain_triple_service_small")
    quad = get_point_benefit_item("entertain_quad_service_small")

    assert is_service_bonus_allowed_for_rule(rule, triple, player_count=3)
    assert not is_service_bonus_allowed_for_rule(rule, triple, player_count=4)
    assert is_service_bonus_allowed_for_rule(rule, quad, player_count=4)

    game = adapt_point_benefit_for_rule(rule, triple)
    assert game["kind"] == "extra_games"
    assert game["games"] == 1
    assert game["seat_count"] == 3
    assert "1 局" in game["name"]


def test_technical_and_entertainment_rewards_cannot_cross_tiers():
    entertain = get_point_benefit_item("entertain_single_service_small")
    tech = get_point_benefit_item("tech_single_service_small")

    entertainment_rule = ORDER_RULES["basic_entertain_single"]
    technical_rule = ORDER_RULES["basic_tech_secret_single"]

    assert is_service_bonus_allowed_for_rule(entertainment_rule, entertain)
    assert not is_service_bonus_allowed_for_rule(entertainment_rule, tech)
    assert is_service_bonus_allowed_for_rule(technical_rule, tech)
    assert not is_service_bonus_allowed_for_rule(technical_rule, entertain)


def test_black_tide_rules_use_owner_approved_prices_and_staff_counts():
    expected = {
        "basic_black_tide_entertain_1": (320, 1),
        "basic_black_tide_entertain_2": (600, 2),
        "basic_black_tide_entertain_3": (900, 3),
        "basic_black_tide_entertain_4": (1200, 4),
        "basic_black_tide_tech_1": (400, 1),
        "basic_black_tide_tech_2": (760, 2),
        "basic_black_tide_tech_3": (1140, 3),
        "basic_black_tide_tech_4": (1520, 4),
    }
    for key, (price, staff_count) in expected.items():
        rule = ORDER_RULES[key]
        assert rule.price == price
        assert rule.required_staff_count == staff_count
        assert rule.player_count_enabled is False
        assert rule.price_multiply_player_count is False


def test_black_tide_entertainment_shares_existing_loyalty_pool():
    scope = loyalty_scope_key("basic_entertain_single")
    for count in range(1, 5):
        assert loyalty_scope_key(f"basic_black_tide_entertain_{count}") == scope


def test_lol_rank_aram_variants_reuse_ng_hourly_price_and_default_points_off():
    for aram_key, ng_key in (
        ("lol_master_aram", "lol_master_ng"),
        ("lol_grandmaster_aram", "lol_grandmaster_ng"),
        ("lol_elite_aram", "lol_elite_ng"),
    ):
        aram_rule = ORDER_RULES[aram_key]
        ng_rule = ORDER_RULES[ng_key]
        assert aram_rule.pricing_type == "hourly"
        assert aram_rule.price == ng_rule.price
        assert aram_rule.required_staff_count == "player_count"
        assert aram_rule.player_count_enabled is True
        assert aram_rule.point_benefits_allowed is False


def test_gendered_entertainment_variants_reuse_existing_roles_and_counts():
    cases = {
        "basic_entertain_female_single": (("female_companion",), 1),
        "basic_entertain_male_single": (("male_companion",), 1),
        "basic_entertain_female_double": (("female_companion",), 2),
        "basic_entertain_male_double": (("male_companion",), 2),
        "basic_mobile_entertain_female_single": (("female_companion",), 1),
        "basic_mobile_entertain_male_single": (("male_companion",), 1),
        "basic_mobile_entertain_female_double": (("female_companion",), 2),
        "basic_mobile_entertain_male_double": (("male_companion",), 2),
    }

    for key, (roles, count) in cases.items():
        rule = ORDER_RULES[key]
        assert rule.allowed_roles == roles
        assert rule.required_staff_count == count
        assert rule.loyalty_benefits_enabled is True

    assert set(ORDER_RULES["basic_entertain_single"].allowed_roles) == {
        "male_companion",
        "female_companion",
    }
    assert set(ORDER_RULES["basic_entertain_double"].allowed_roles) == {
        "male_companion",
        "female_companion",
    }


def test_gendered_variants_share_existing_entertainment_loyalty_pool():
    desktop_scope = loyalty_scope_key("basic_entertain_single")
    assert loyalty_scope_key("basic_entertain_double") == desktop_scope
    assert loyalty_scope_key("basic_entertain_female_single") == desktop_scope
    assert loyalty_scope_key("basic_entertain_male_single") == desktop_scope
    assert loyalty_scope_key("basic_entertain_female_double") == desktop_scope
    assert loyalty_scope_key("basic_entertain_male_double") == desktop_scope

    mobile_scope = loyalty_scope_key("basic_mobile_entertain_single")
    assert loyalty_scope_key("basic_mobile_entertain_double") == mobile_scope
    assert loyalty_scope_key("basic_mobile_entertain_female_single") == mobile_scope
    assert loyalty_scope_key("basic_mobile_entertain_male_double") == mobile_scope


def test_self_service_third_field_uses_mode_and_one_to_four_seats():
    black_tide = _group("delta_desktop_basic", "黑潮爆破")
    assert [item["label"] for item in black_tide["details"]] == [
        "娛樂單陪｜320T / H",
        "娛樂雙陪｜600T / H",
        "娛樂三陪｜900T / H",
        "娛樂四陪｜1200T / H",
        "技術單陪｜400T / H",
        "技術雙陪｜760T / H",
        "技術三陪｜1140T / H",
        "技術四陪｜1520T / H",
    ]

    steam = _group("steam", "娛樂陪")
    steam_details = [
        item for item in steam["details"] if item.get("rule_key") == "steam_play"
    ]
    assert [item["label"] for item in steam_details] == ["單陪", "雙陪", "三陪", "四陪"]

    valorant_entertain = _group("valorant", "娛樂陪")
    assert [item["label"] for item in valorant_entertain["details"]] == [
        "NG 單陪", "NG 雙陪", "NG 三陪", "NG 四陪",
        "RK 單陪", "RK 雙陪", "RK 三陪", "RK 四陪",
    ]

    lol_entertain = _group("lol", "娛樂陪")
    assert [item["label"] for item in lol_entertain["details"]] == [
        "NG 單陪", "NG 雙陪", "NG 三陪", "NG 四陪",
        "RK 單陪", "RK 雙陪", "RK 三陪", "RK 四陪",
        "AR 單陪", "AR 雙陪", "AR 三陪", "AR 四陪",
    ]


def test_self_service_rank_groups_keep_dynamic_hour_and_game_units():
    valorant_rank = _group("valorant", "超凡陪")
    assert [item["label"] for item in valorant_rank["details"]] == [
        "NG 單陪", "NG 雙陪", "NG 三陪", "NG 四陪",
        "RK 單陪", "RK 雙陪", "RK 三陪", "RK 四陪",
    ]
    assert {item["quantity_unit"] for item in valorant_rank["details"] if item["label"].startswith("NG ")} == {"小時"}
    assert {item["quantity_unit"] for item in valorant_rank["details"] if item["label"].startswith("RK ")} == {"局"}

    lol_rank_groups = [
        group
        for group in SELF_SERVICE_ORDER_CATALOG["lol"]
        if str(group.get("label") or "") != "娛樂陪"
        and any(str(item.get("value") or "").startswith("ranked_") for item in group.get("details", []))
    ]
    assert lol_rank_groups
    expected_labels = [
        "NG 單陪", "NG 雙陪", "NG 三陪", "NG 四陪",
        "RK 單陪", "RK 雙陪", "RK 三陪", "RK 四陪",
        "AR 單陪", "AR 雙陪", "AR 三陪", "AR 四陪",
    ]
    for group in lol_rank_groups:
        assert [item["label"] for item in group["details"]] == expected_labels
        assert {item["quantity_unit"] for item in group["details"] if item["label"].startswith(("NG ", "AR "))} == {"小時"}
        assert {item["quantity_unit"] for item in group["details"] if item["label"].startswith("RK ")} == {"局"}


def test_legacy_one_seat_helper_stays_compatible_for_old_orders():
    double_rule = ORDER_RULES["basic_entertain_double"]
    value = calculate_one_seat_service_bonus_value(
        rule=double_rule,
        service_original=1200,
        quantity=2,
        player_count=1,
        extra_hours=1,
    )
    assert value == 300


def test_web_checkout_uses_same_new_catalog_and_filters_fixed_seat_rewards():
    web_keys = {item["key"] for item in WEB_POINT_ITEMS}
    assert web_keys == {item["key"] for item in POINT_REDEEM_ITEMS}
    assert "entertain_service_large" not in web_keys
    assert "entertain_service_large" in WEB_POINT_ITEM_MAP

    options = list_point_options(
        rule_key="basic_entertain_double",
        point_balance=999,
        quantity=1,
        has_specified_staff=False,
    )
    by_key = {item["key"]: item for item in options}
    assert by_key["entertain_double_service_small"]["allowed"] is True
    assert by_key["entertain_double_service_small"]["kind"] == "extra_hours"
    assert by_key["entertain_double_service_small"]["hours"] == 0.5
    assert by_key["entertain_single_service_small"]["allowed"] is False
    assert by_key["entertain_triple_service_small"]["allowed"] is False
    assert by_key["tech_double_service_small"]["allowed"] is False


def test_web_double_service_reward_funds_both_companion_seats():
    item = adapt_point_benefit_for_rule(
        ORDER_RULES["basic_entertain_double"],
        get_point_benefit_item("entertain_double_service_large"),
    )
    assert calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 2,
            "customer_pay_amount": 1200,
        },
        vip_pay_rate=100,
        point_item=item,
    ) == 600


def test_web_quad_service_reward_funds_all_four_companion_seats():
    item = adapt_point_benefit_for_rule(
        ORDER_RULES["basic_black_tide_entertain_4"],
        get_point_benefit_item("entertain_quad_service_large"),
    )
    assert calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 4,
            "customer_pay_amount": 2400,
        },
        vip_pay_rate=100,
        point_item=item,
    ) == 1200


def test_web_single_service_reward_funds_one_companion_seat():
    item = adapt_point_benefit_for_rule(
        ORDER_RULES["basic_entertain_single"],
        get_point_benefit_item("entertain_single_service_large"),
    )
    assert calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 1,
            "customer_pay_amount": 640,
        },
        vip_pay_rate=100,
        point_item=item,
    ) == 320
