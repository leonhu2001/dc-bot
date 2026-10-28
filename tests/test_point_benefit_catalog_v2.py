from services.loyalty_benefits import loyalty_scope_key
from services.order_rules import ORDER_RULES
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


def test_point_catalog_splits_single_and_double_service_rewards():
    assert _catalog_costs() == {
        "discount_50": 20,
        "free_specify_fee": 30,
        "discount_100": 45,
        "entertain_single_service_small": 80,
        "entertain_single_service_large": 140,
        "entertain_double_service_small": 160,
        "entertain_double_service_large": 280,
        "tech_single_service_small": 110,
        "tech_single_service_large": 200,
        "tech_double_service_small": 220,
        "tech_double_service_large": 400,
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


def test_entertainment_single_and_double_rewards_match_exact_seat_count():
    single = get_point_benefit_item("entertain_single_service_small")
    double = get_point_benefit_item("entertain_double_service_small")
    single_rule = ORDER_RULES["basic_entertain_single"]
    double_rule = ORDER_RULES["basic_entertain_double"]

    assert is_service_bonus_allowed_for_rule(single_rule, single)
    assert not is_service_bonus_allowed_for_rule(single_rule, double)
    assert is_service_bonus_allowed_for_rule(double_rule, double)
    assert not is_service_bonus_allowed_for_rule(double_rule, single)

    hourly = adapt_point_benefit_for_rule(double_rule, double)
    assert hourly["kind"] == "extra_hours"
    assert hourly["hours"] == 0.5
    assert hourly["seat_count"] == 2
    assert "雙陪" in hourly["name"]
    assert "2 位陪玩同步加贈" in hourly["summary"]


def test_entertainment_reward_adapts_to_game_and_preserves_seat_requirement():
    benefit = get_point_benefit_item("entertain_single_service_small")
    game_rule = ORDER_RULES["valorant_entertain_ranked"]

    assert is_service_bonus_allowed_for_rule(game_rule, benefit)
    game = adapt_point_benefit_for_rule(game_rule, benefit)
    assert game["kind"] == "extra_games"
    assert game["games"] == 1
    assert game["seat_count"] == 1
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
