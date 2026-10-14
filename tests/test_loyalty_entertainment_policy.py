from services import loyalty_benefits as loyalty
from services import order_rules
from services.order_rules import ORDER_RULES


ELIGIBLE_RULES = {
    "basic_entertain_single",
    "basic_entertain_double",
    "basic_mobile_entertain_single",
    "basic_mobile_entertain_double",
    "steam_play",
    "valorant_entertain_ng",
    "lol_entertain_aram",
    "lol_entertain_ng",
    "apex_entertain_ng",
}


def test_only_entertainment_non_ranked_modes_have_loyalty_progress():
    enabled_rule_keys = {
        rule_key
        for rule_key, rule in order_rules._BASE_ORDER_RULES.items()
        if rule.loyalty_benefits_enabled
    }
    assert enabled_rule_keys == ELIGIBLE_RULES

    for rule_key in ELIGIBLE_RULES:
        assert ORDER_RULES[rule_key].loyalty_benefits_enabled is True
        policy = loyalty.loyalty_policy_for_rule(rule_key)
        assert policy is not None
        assert policy["pricing_type"] == "hourly"
        assert policy["threshold_units"] == 10.0
        assert policy["benefit_units"] == 1.0
        assert policy["benefit_label"] == "+1 小時"
