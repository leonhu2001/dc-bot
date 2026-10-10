from services.order_rules import ORDER_RULES


def test_current_builtin_rules_no_longer_use_same_order_buy_get():
    active = [
        rule.key for rule in ORDER_RULES.values()
        if rule.service_bonus_buy or rule.service_bonus_gift
    ]
    assert active == []


def test_legacy_valorant_rules_are_not_active():
    assert "valorant_entertain" not in ORDER_RULES
    assert "valorant_tech" not in ORDER_RULES
    assert "valorant_top_tech" not in ORDER_RULES


def test_loyalty_thresholds_are_split_by_hour_and_game():
    hourly = ORDER_RULES["basic_entertain_single"]
    assert hourly.loyalty_threshold_units == 10
    assert hourly.loyalty_reward_units == 0.5
    game = ORDER_RULES["valorant_entertain_ranked"]
    assert game.loyalty_threshold_units == 20
    assert game.loyalty_reward_units == 1
    apex = ORDER_RULES["apex_entertain_platinum"]
    assert apex.loyalty_threshold_units == 10
    assert apex.loyalty_reward_units == 0.5
    assert ORDER_RULES["steam_play"].loyalty_threshold_units is None
