from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES


ELIGIBLE_RULES = (
    "basic_entertain_single",
    "basic_entertain_double",
    "basic_mobile_entertain_single",
    "basic_mobile_entertain_double",
    "steam_play",
    "valorant_entertain_ng",
    "valorant_entertain_ranked",
    "lol_entertain_aram",
    "lol_entertain_ng",
    "lol_entertain_ranked",
    "apex_entertain_ng",
    "apex_entertain_ranked",
)

INELIGIBLE_RULES = (
    "basic_exbar_tech",
    "basic_tech_secret_single",
    "basic_tech_secret_double",
    "basic_tech_topsecret_single",
    "basic_tech_topsecret_double",
    "basic_mobile_tech_secret_single",
    "basic_mobile_tech_secret_double",
    "basic_mobile_tech_topsecret_single",
    "basic_mobile_tech_topsecret_double",
    "valorant_ascendant_ng",
    "valorant_ascendant_ranked",
    "valorant_immortal_ng",
    "valorant_immortal_ranked",
    "valorant_radiant_ng",
    "valorant_radiant_ranked",
    "lol_master_ng",
    "lol_master_ranked",
    "lol_grandmaster_ng",
    "lol_grandmaster_ranked",
    "lol_elite_ng",
    "lol_elite_ranked",
    "apex_diamond_ng",
    "apex_diamond_ranked",
    "apex_master_ng",
    "apex_master_ranked",
    "apex_predator_ng",
    "apex_predator_ranked",
)


def test_only_entertainment_products_have_loyalty_progress():
    for rule_key in ELIGIBLE_RULES:
        rule = ORDER_RULES[rule_key]
        assert rule.loyalty_benefits_enabled is True
        policy = loyalty.loyalty_policy_for_rule(rule_key)
        assert policy is not None
        expected_threshold = 15.0 if policy["pricing_type"] == "game" else 10.0
        assert policy["threshold_units"] == expected_threshold
        assert policy["benefit_units"] == 1.0

    for rule_key in INELIGIBLE_RULES:
        assert ORDER_RULES[rule_key].loyalty_benefits_enabled is False
        assert loyalty.loyalty_policy_for_rule(rule_key) is None


def test_ranked_game_entertainment_uses_fifteen_game_reward_threshold():
    assert loyalty.loyalty_policy_for_rule("valorant_entertain_ranked") == {
        "pricing_type": "game",
        "threshold_units": 15.0,
        "benefit_kind": "extra_games",
        "benefit_units": 1.0,
        "unit_label": "局",
        "benefit_label": "+1 局",
    }
    assert loyalty.loyalty_policy_for_rule("apex_entertain_ranked")["pricing_type"] == "hourly"
    assert loyalty.loyalty_policy_for_rule("apex_entertain_ranked")["threshold_units"] == 10.0
