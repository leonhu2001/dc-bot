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


def test_point_catalog_v2_has_compact_non_vip_rewards():
    assert _catalog_costs() == {
        "discount_50": 25,
        "free_specify_fee": 30,
        "discount_100": 45,
        "entertain_service_small": 80,
        "tech_service_small": 110,
        "entertain_service_large": 140,
        "tech_service_large": 200,
    }
    assert all("vip" not in item["key"].lower() for item in POINT_REDEEM_ITEMS)


def test_legacy_point_keys_are_lookup_only():
    selectable_keys = {item["key"] for item in POINT_REDEEM_ITEMS}
    assert "discount_20" not in selectable_keys
    assert "discount_30" not in selectable_keys
    assert "extra_hour_1h" not in selectable_keys
    assert "extra_game_2" not in selectable_keys

    assert "discount_20" in LEGACY_POINT_REDEEM_ITEMS_BY_KEY
    assert get_point_benefit_item("discount_20")["amount"] == 20
    assert get_point_benefit_item("extra_game_2")["games"] == 2


def test_entertainment_reward_adapts_to_hourly_or_game():
    benefit = get_point_benefit_item("entertain_service_small")

    hourly_rule = ORDER_RULES["basic_entertain_single"]
    assert is_service_bonus_allowed_for_rule(hourly_rule, benefit)
    hourly = adapt_point_benefit_for_rule(hourly_rule, benefit)
    assert hourly["kind"] == "extra_hours"
    assert hourly["hours"] == 0.5
    assert "30 分鐘" in hourly["name"]

    game_rule = ORDER_RULES["valorant_entertain_ranked"]
    assert is_service_bonus_allowed_for_rule(game_rule, benefit)
    game = adapt_point_benefit_for_rule(game_rule, benefit)
    assert game["kind"] == "extra_games"
    assert game["games"] == 1
    assert "1 局" in game["name"]


def test_technical_and_entertainment_rewards_cannot_cross_tiers():
    entertain = get_point_benefit_item("entertain_service_small")
    tech = get_point_benefit_item("tech_service_small")

    entertainment_rule = ORDER_RULES["basic_entertain_single"]
    technical_rule = ORDER_RULES["basic_tech_secret_single"]

    assert is_service_bonus_allowed_for_rule(entertainment_rule, entertain)
    assert not is_service_bonus_allowed_for_rule(entertainment_rule, tech)
    assert is_service_bonus_allowed_for_rule(technical_rule, tech)
    assert not is_service_bonus_allowed_for_rule(technical_rule, entertain)


def test_one_point_voucher_only_funds_one_companion_seat():
    double_rule = ORDER_RULES["basic_entertain_double"]

    # 2 hours x 600T double-companion price = 1,200T total service value.
    # A +1H voucher funds one companion seat only: 600 / 2 = 300T.
    value = calculate_one_seat_service_bonus_value(
        rule=double_rule,
        service_original=1200,
        quantity=2,
        player_count=1,
        extra_hours=1,
    )
    assert value == 300


def test_web_checkout_uses_same_catalog_and_adaptation():
    web_keys = {item["key"] for item in WEB_POINT_ITEMS}
    assert web_keys == {item["key"] for item in POINT_REDEEM_ITEMS}
    assert "extra_hour_1h" not in web_keys
    assert "extra_hour_1h" in WEB_POINT_ITEM_MAP

    options = list_point_options(
        rule_key="valorant_entertain_ranked",
        point_balance=999,
        quantity=1,
        has_specified_staff=False,
    )
    by_key = {item["key"]: item for item in options}
    assert by_key["entertain_service_small"]["allowed"] is True
    assert by_key["entertain_service_small"]["kind"] == "extra_games"
    assert by_key["entertain_service_small"]["games"] == 1
    assert by_key["tech_service_small"]["allowed"] is False


def test_web_service_value_divides_multi_companion_orders_by_seat():
    item = adapt_point_benefit_for_rule(
        ORDER_RULES["basic_entertain_double"],
        get_point_benefit_item("entertain_service_large"),
    )
    assert calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 2,
            "customer_pay_amount": 1200,
        },
        vip_pay_rate=100,
        point_item=item,
    ) == 300
