from services.loyalty_benefits import loyalty_scope_key
from services.multi_seat_order_policy_20261028 import (
    get_player_count_price_table,
    get_rule_player_count_bounds,
    is_service_point_benefit_enabled,
)
from services.order_rules import ORDER_RULES, calculate_price
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.point_benefit_catalog import (
    LEGACY_POINT_REDEEM_ITEMS_BY_KEY,
    POINT_REDEEM_ITEMS,
    adapt_point_benefit_for_rule,
    calculate_one_seat_service_bonus_value,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)
from services.self_service_point_benefits import is_order_point_benefit_allowed_for_rule
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


def test_shared_player_count_controls_service_voucher_seat_match():
    rule = ORDER_RULES["basic_black_tide_entertain"]
    benefits = {
        1: get_point_benefit_item("entertain_single_service_small"),
        2: get_point_benefit_item("entertain_double_service_small"),
        3: get_point_benefit_item("entertain_triple_service_small"),
        4: get_point_benefit_item("entertain_quad_service_small"),
    }
    for selected_count in range(1, 5):
        for benefit_count, benefit in benefits.items():
            assert is_service_bonus_allowed_for_rule(
                rule,
                benefit,
                player_count=selected_count,
            ) is (selected_count == benefit_count)

    adapted = adapt_point_benefit_for_rule(rule, benefits[4])
    assert adapted["kind"] == "extra_hours"
    assert adapted["hours"] == 0.5
    assert adapted["seat_count"] == 4
    assert "4陪" in adapted["name"]


def test_delta_companion_type_and_count_are_separate_but_legacy_double_rules_remain():
    for key, roles in (
        ("basic_entertain_single", {"male_companion", "female_companion"}),
        ("basic_entertain_female_single", {"female_companion"}),
        ("basic_entertain_male_single", {"male_companion"}),
        ("basic_mobile_entertain_single", {"male_companion", "female_companion"}),
        ("basic_mobile_entertain_female_single", {"female_companion"}),
        ("basic_mobile_entertain_male_single", {"male_companion"}),
    ):
        rule = ORDER_RULES[key]
        assert set(rule.allowed_roles) == roles
        assert rule.required_staff_count == "player_count"
        assert get_rule_player_count_bounds(rule) == (1, 2, 1, True)

    for legacy_key in (
        "basic_entertain_double",
        "basic_entertain_female_double",
        "basic_entertain_male_double",
        "basic_mobile_entertain_double",
        "basic_mobile_entertain_female_double",
        "basic_mobile_entertain_male_double",
    ):
        assert legacy_key in ORDER_RULES
        assert ORDER_RULES[legacy_key].required_staff_count == 2


def test_delta_catalog_shows_type_only_and_keeps_old_single_selector_value():
    for category in ("delta_desktop_basic", "delta_mobile_basic"):
        group = _group(category, "娛樂陪")
        assert [item["label"] for item in group["details"]] == ["不限", "女陪", "男陪"]
        assert group["details"][0]["value"] in {"single", "mobile_single"}
        assert all("player_count" not in item for item in group["details"])


def test_black_tide_and_steam_use_explicit_one_to_four_price_tables():
    black_entertain = ORDER_RULES["basic_black_tide_entertain"]
    black_tech = ORDER_RULES["basic_black_tide_tech"]
    steam = ORDER_RULES["steam_play"]
    assert get_player_count_price_table(black_entertain) == {1: 320, 2: 600, 3: 900, 4: 1200}
    assert get_player_count_price_table(black_tech) == {1: 400, 2: 760, 3: 1140, 4: 1520}
    assert get_player_count_price_table(steam) == {1: 320, 2: 640, 3: 960, 4: 1280}

    assert [calculate_price(black_entertain, quantity=1, player_count=count).base_amount for count in range(1, 5)] == [320, 600, 900, 1200]
    assert [calculate_price(black_tech, quantity=1, player_count=count).base_amount for count in range(1, 5)] == [400, 760, 1140, 1520]
    assert [calculate_price(steam, quantity=1, player_count=count).base_amount for count in range(1, 5)] == [320, 640, 960, 1280]

    for rule in (black_entertain, black_tech):
        assert rule.required_staff_count == "player_count"
        assert rule.player_count_enabled is True
        assert get_rule_player_count_bounds(rule) == (1, 4, 1, True)

    black_group = _group("delta_desktop_basic", "黑潮爆破")
    assert [item["label"] for item in black_group["details"]] == ["娛樂陪", "技術陪"]
    steam_group = _group("steam", "娛樂陪")
    assert [item["label"] for item in steam_group["details"]] == ["娛樂陪"]


def test_black_tide_legacy_fixed_seat_keys_are_removed_from_active_rules():
    legacy_keys = {
        f"basic_black_tide_{tier}_{count}"
        for tier in ("entertain", "tech")
        for count in range(1, 5)
    }
    assert legacy_keys.isdisjoint(ORDER_RULES)


def test_game_catalog_third_field_contains_mode_only_and_count_is_rule_bound():
    valorant = _group("valorant", "超凡陪")
    assert [item["label"] for item in valorant["details"]] == ["NG", "RK"]
    assert [item["quantity_unit"] for item in valorant["details"]] == ["小時", "局"]
    assert all("player_count" not in item for item in valorant["details"])

    lol = _group("lol", "大師陪")
    assert [item["label"] for item in lol["details"]] == ["NG", "RK", "AR"]
    assert [item["quantity_unit"] for item in lol["details"]] == ["小時", "局", "小時"]
    assert all("player_count" not in item for item in lol["details"])

    apex = _group("apex", "大師陪")
    assert [item["label"] for item in apex["details"]] == ["NG", "積分"]
    assert all("player_count" not in item for item in apex["details"])

    assert get_rule_player_count_bounds(ORDER_RULES["valorant_ascendant_ng"]) == (1, 4, 1, True)
    assert get_rule_player_count_bounds(ORDER_RULES["lol_master_ng"]) == (1, 4, 1, True)
    assert get_rule_player_count_bounds(ORDER_RULES["apex_master_ng"]) == (1, 2, 1, True)


def test_lol_rank_aram_variants_reuse_ng_price_and_support_service_points():
    for aram_key, ng_key in (
        ("lol_master_aram", "lol_master_ng"),
        ("lol_grandmaster_aram", "lol_grandmaster_ng"),
        ("lol_elite_aram", "lol_elite_ng"),
    ):
        aram_rule = ORDER_RULES[aram_key]
        assert aram_rule.pricing_type == "hourly"
        assert aram_rule.price == ORDER_RULES[ng_key].price
        assert aram_rule.point_benefits_allowed is True
        assert is_service_point_benefit_enabled(aram_rule) is True

        assert is_order_point_benefit_allowed_for_rule(
            aram_rule,
            "discount_50",
            {"player_count": 1, "quantity": 1},
        )[0] is True
        assert is_order_point_benefit_allowed_for_rule(
            aram_rule,
            "tech_single_service_small",
            {"player_count": 1, "quantity": 1},
        )[0] is True


def test_lol_valorant_apex_enable_service_point_rewards_and_cash_points():
    for rule_key in (
        "valorant_entertain_ng",
        "lol_entertain_ng",
        "apex_entertain_ng",
    ):
        rule = ORDER_RULES[rule_key]
        assert is_order_point_benefit_allowed_for_rule(
            rule,
            "discount_50",
            {"player_count": 1, "quantity": 1},
        )[0] is True
        allowed, reason = is_order_point_benefit_allowed_for_rule(
            rule,
            "entertain_single_service_small",
            {"player_count": 1, "quantity": 1},
        )
        assert allowed is True
        assert reason == ""


def test_entertainment_loyalty_scopes_remain_shared():
    desktop_scope = loyalty_scope_key("basic_entertain_single")
    for key in (
        "basic_entertain_double",
        "basic_entertain_female_single",
        "basic_entertain_male_single",
        "basic_black_tide_entertain",
    ):
        assert loyalty_scope_key(key) == desktop_scope


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


def test_web_catalog_keeps_current_service_rewards_and_legacy_keys_internal():
    web_keys = {item["key"] for item in WEB_POINT_ITEMS}
    assert web_keys == {item["key"] for item in POINT_REDEEM_ITEMS}
    assert "entertain_service_large" not in web_keys
    assert "entertain_service_large" in WEB_POINT_ITEM_MAP

    options = list_point_options(
        rule_key="basic_entertain_single",
        point_balance=999,
        quantity=1,
        has_specified_staff=False,
        player_count=2,
    )
    by_key = {item["key"]: item for item in options}
    assert by_key["entertain_double_service_small"]["allowed"] is True
    assert by_key["entertain_double_service_small"]["hours"] == 0.5
    assert by_key["entertain_single_service_small"]["allowed"] is False
    assert by_key["tech_double_service_small"]["allowed"] is False


def test_web_multi_seat_service_reward_funds_all_selected_seats():
    item = adapt_point_benefit_for_rule(
        ORDER_RULES["basic_black_tide_entertain"],
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
