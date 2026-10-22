from services.order_rules import (
    ALL_ROLE_IDS,
    calculate_price,
    get_allowed_role_ids,
    get_required_game_role_ids,
    get_rule,
    role_ids_match_requirements,
)
from services.orders import get_order_item_details_for_group
from shared.order_acceptance import EXACT_ONE_PROTECTOR_RULE_KEYS


DESKTOP_SECRET = "basic_one_companion_one_guard_secret"
DESKTOP_TOPSECRET = "basic_one_companion_one_guard_topsecret"
MOBILE_SECRET = "basic_mobile_one_companion_one_guard_secret"
MOBILE_TOPSECRET = "basic_mobile_one_companion_one_guard_topsecret"


def test_one_companion_one_guard_prices_and_staffing():
    expected = {
        DESKTOP_SECRET: (720, "delta_desktop_basic", "delta_desktop"),
        DESKTOP_TOPSECRET: (770, "delta_desktop_basic", "delta_desktop"),
        MOBILE_SECRET: (720, "delta_mobile_basic", "delta_mobile"),
        MOBILE_TOPSECRET: (770, "delta_mobile_basic", "delta_mobile"),
    }

    for key, (price, category, game_role) in expected.items():
        rule = get_rule(key)
        assert rule.category == category
        assert rule.price == price
        assert rule.pricing_type == "hourly"
        assert rule.unit_label == "H"
        assert rule.required_staff_count == 2
        assert rule.min_protector_count == 1
        assert rule.min_quantity == 1
        assert rule.max_quantity == 24
        assert rule.required_game_roles == (game_role,)

        quote = calculate_price(rule, quantity=3)
        assert quote.total_amount == price * 3
        assert quote.required_staff_count == 2


def test_one_companion_one_guard_requires_matching_delta_platform_role():
    rule = get_rule(DESKTOP_SECRET)
    allowed = get_allowed_role_ids(rule)
    required_games = get_required_game_role_ids(rule)

    companion_id = ALL_ROLE_IDS["male_companion"]
    protector_id = ALL_ROLE_IDS["female_protector"]
    desktop_id = ALL_ROLE_IDS["delta_desktop"]
    mobile_id = ALL_ROLE_IDS["delta_mobile"]

    assert role_ids_match_requirements(
        [companion_id, desktop_id], allowed, required_games
    )
    assert role_ids_match_requirements(
        [protector_id, desktop_id], allowed, required_games
    )
    assert not role_ids_match_requirements([companion_id], allowed, required_games)
    assert not role_ids_match_requirements(
        [companion_id, mobile_id], allowed, required_games
    )


def test_one_companion_one_guard_requires_exactly_one_protector_slot():
    expected_rule_keys = {
        DESKTOP_SECRET,
        DESKTOP_TOPSECRET,
        MOBILE_SECRET,
        MOBILE_TOPSECRET,
    }

    assert expected_rule_keys <= EXACT_ONE_PROTECTOR_RULE_KEYS


def test_one_companion_one_guard_catalog_has_clear_difficulty_choices():
    desktop = get_order_item_details_for_group("delta_desktop_basic", "一陪一護")
    mobile = get_order_item_details_for_group("delta_mobile_basic", "一陪一護")

    assert [(item["label"], item["rule_key"]) for item in desktop] == [
        ("機密", DESKTOP_SECRET),
        ("絕密", DESKTOP_TOPSECRET),
    ]
    assert [(item["label"], item["rule_key"]) for item in mobile] == [
        ("機密", MOBILE_SECRET),
        ("絕密", MOBILE_TOPSECRET),
    ]

    for item in desktop + mobile:
        assert item["quantity_unit"] == "小時"
        assert item["min_quantity"] == 1
        assert item["max_quantity"] == 24
