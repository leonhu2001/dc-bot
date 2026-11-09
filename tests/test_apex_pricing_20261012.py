from services.loyalty_benefits import loyalty_policy_for_rule
from services.multi_seat_order_policy_20261028 import get_rule_player_count_bounds
from services.order_rules import ORDER_RULES, calculate_price
from services.orders import get_order_item_details_for_group
from web.app.services.order_groups import get_grouped_order_catalog


ACTIVE_APEX_PRICES = {
    "apex_entertain_ng": 320,
    "apex_entertain_ranked": 350,
    "apex_diamond_ng": 380,
    "apex_diamond_ranked": 400,
    "apex_master_ng": 400,
    "apex_master_ranked": 450,
    "apex_predator_ng": 500,
    "apex_predator_ranked": 550,
}


def test_apex_new_pricing_is_fixed_per_person_per_hour():
    for rule_key, price in ACTIVE_APEX_PRICES.items():
        rule = ORDER_RULES[rule_key]
        assert rule.category == "apex"
        assert rule.pricing_type == "hourly"
        assert rule.unit_label == "H"
        assert rule.price == price
        assert rule.required_staff_count == "player_count"
        assert rule.player_count_enabled is True
        assert rule.min_player_count == 1
        assert rule.max_player_count == 2
        assert rule.price_multiply_player_count is True
        assert rule.allow_specify is True
        assert rule.max_specified_count == 2
        assert rule.specify_fee_default == 100
        assert rule.specify_free_min_units == 2
        assert rule.specify_free_basis == "quantity"
        assert rule.loyalty_benefits_enabled is rule_key.startswith("apex_entertain_")


def test_apex_double_predator_ranked_two_hours_costs_2200():
    result = calculate_price(
        ORDER_RULES["apex_predator_ranked"],
        quantity=2,
        player_count=2,
    )
    assert result.base_amount == 2200
    assert result.specify_fee == 0
    assert result.total_amount == 2200
    assert result.required_staff_count == 2


def test_apex_specify_fee_is_100_each_and_free_from_two_hours():
    rule = ORDER_RULES["apex_diamond_ng"]
    specified = ["apex_master", "apex_predator"]

    one_hour = calculate_price(
        rule,
        quantity=1,
        player_count=2,
        specified_roles=specified,
    )
    assert one_hour.base_amount == 760
    assert one_hour.specify_fee == 200
    assert one_hour.total_amount == 960
    assert one_hour.free_specify_fee is False

    two_hours = calculate_price(
        rule,
        quantity=2,
        player_count=2,
        specified_roles=specified,
    )
    assert two_hours.base_amount == 1520
    assert two_hours.specify_fee == 0
    assert two_hours.total_amount == 1520
    assert two_hours.free_specify_fee is True


def test_apex_loyalty_only_applies_to_entertainment_at_ten_percent():
    policy = loyalty_policy_for_rule("apex_entertain_ranked")
    assert policy is not None
    assert policy["pricing_type"] == "hourly"
    assert policy["threshold_units"] == 10.0
    assert policy["benefit_kind"] == "extra_hours"
    assert policy["benefit_units"] == 1.0
    assert policy["benefit_label"] == "+1 小時"
    assert loyalty_policy_for_rule("apex_predator_ranked") is None


def test_apex_web_catalog_exposes_new_ranked_price_tiers():
    groups = {
        group["key"]: group
        for group in get_grouped_order_catalog("apex")
    }

    for group_key, rule_prefix in (
        ("apex_entertain", "apex_entertain"),
        ("apex_diamond", "apex_diamond"),
        ("apex_master", "apex_master"),
        ("apex_predator", "apex_predator"),
    ):
        group = groups[group_key]
        assert group["selector_label"] == "模式"
        assert [variant["rule_key"] for variant in group["variants"]] == [
            f"{rule_prefix}_ng",
            f"{rule_prefix}_ranked",
            f"{rule_prefix}_ranked_tier_diamond",
            f"{rule_prefix}_ranked_tier_master",
            f"{rule_prefix}_ranked_tier_predator",
        ]
        assert [variant["label"] for variant in group["variants"]] == [
            "NG",
            "積分（白金以下）",
            "積分（鑽石）",
            "積分（大師）",
            "積分（頂獵）",
        ]
        assert "每往上一階" in group["description"]
        assert all(not variant["customer_adjustments"] for variant in group["variants"])
        assert "老闆目前段位" not in group["description"]
        assert "買 5 送 1" not in group["description"]
        assert "累積 10H 送 30 分鐘券" not in group["description"]
        if group_key == "apex_entertain":
            assert "累積 10 個服務小時回饋 1 小時" in group["description"]
            assert "達標當單直接折抵" in group["description"]
        else:
            assert "回饋" not in group["description"]


def test_apex_discord_catalog_includes_ranked_tiers_with_separate_player_count():
    for group_label, rule_prefix in (
        ("娛樂陪", "apex_entertain"),
        ("鑽石陪", "apex_diamond"),
        ("大師陪", "apex_master"),
        ("頂獵陪", "apex_predator"),
    ):
        details = get_order_item_details_for_group("apex", group_label)
        assert [item["label"] for item in details] == [
            "NG", "積分（白金以下）", "積分（鑽石）", "積分（大師）", "積分（頂獵）",
        ]
        assert [item["rule_key"] for item in details] == [
            f"{rule_prefix}_ng",
            f"{rule_prefix}_ranked",
            f"{rule_prefix}_ranked_tier_diamond",
            f"{rule_prefix}_ranked_tier_master",
            f"{rule_prefix}_ranked_tier_predator",
        ]
        assert all("player_count" not in item for item in details)
        assert get_rule_player_count_bounds(ORDER_RULES[f"{rule_prefix}_ng"]) == (1, 2, 1, True)



def test_apex_ranked_adds_50_per_tier_per_worker_per_hour():
    base_by_prefix = {
        "apex_entertain": 350,
        "apex_diamond": 400,
        "apex_master": 450,
        "apex_predator": 550,
    }
    for prefix, base_price in base_by_prefix.items():
        for tier, steps in (("diamond", 1), ("master", 2), ("predator", 3)):
            rule_key = f"{prefix}_ranked_tier_{tier}"
            rule = ORDER_RULES[rule_key]
            assert rule.price == base_price + 50 * steps
            assert rule.pricing_type == "hourly"
            assert rule.max_player_count == 2
            assert rule.specify_free_min_units == 2
            amount = calculate_price(rule, quantity=2, player_count=2)
            assert amount.base_amount == (base_price + 50 * steps) * 4
            assert amount.total_amount == amount.base_amount
            assert rule.loyalty_benefits_enabled is prefix == "apex_entertain"



def test_apex_legacy_customer_rank_rules_stay_available_for_old_orders():
    legacy = {
        "apex_entertain_diamond": 330,
        "apex_diamond_platinum": 360,
        "apex_master_diamond": 460,
        "apex_predator_diamond": 550,
    }
    for rule_key, price in legacy.items():
        assert rule_key in ORDER_RULES
        assert ORDER_RULES[rule_key].price == price
