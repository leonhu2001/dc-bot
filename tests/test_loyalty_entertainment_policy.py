from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES


ELIGIBLE_RULES = (
    "basic_entertain_single",
    "basic_entertain_double",
    "basic_mobile_entertain_single",
    "basic_mobile_entertain_double",
    "steam_play",
    "valorant_entertain_ng",
    "lol_entertain_aram",
    "lol_entertain_ng",
    "apex_entertain_ng",
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
    "valorant_entertain_ranked",
    "valorant_ascendant_ng",
    "valorant_ascendant_ranked",
    "lol_entertain_ranked",
    "lol_master_ng",
    "lol_master_ranked",
    "apex_entertain_ranked",
    "apex_diamond_ng",
    "apex_diamond_ranked",
)


def test_only_entertainment_non_ranked_modes_have_loyalty_progress():
    for rule_key in ELIGIBLE_RULES:
        assert ORDER_RULES[rule_key].loyalty_benefits_enabled is True
        policy = loyalty.loyalty_policy_for_rule(rule_key)
        assert policy is not None
        assert policy["pricing_type"] == "hourly"
        assert policy["threshold_units"] == 10.0
        assert policy["benefit_units"] == 1.0
        assert policy["benefit_label"] == "+1 小時"

    for rule_key in INELIGIBLE_RULES:
        assert ORDER_RULES[rule_key].loyalty_benefits_enabled is False
        assert loyalty.loyalty_policy_for_rule(rule_key) is None
