from services.game_roles import GAME_ROLE_BY_KEY
from services.order_rules import ORDER_RULES, calculate_price, get_allowed_role_ids


def test_lol_master_role_id_is_requested_one():
    assert GAME_ROLE_BY_KEY["lol_master"].role_id == "1545362644607832065"


def test_new_game_tiers_are_independent_from_old_service_roles():
    assert ORDER_RULES["valorant_ascendant_ng"].allowed_roles == ()
    assert ORDER_RULES["lol_master_ng"].allowed_roles == ()
    assert ORDER_RULES["valorant_ascendant_ng"].allowed_game_roles == ("valorant_ascendant", "valorant_immortal", "valorant_radiant")
    assert ORDER_RULES["lol_master_ng"].allowed_game_roles == ("lol_master", "lol_grandmaster", "lol_elite")


def test_entertainment_explicitly_allows_companions_and_game_ranks():
    assert set(ORDER_RULES["valorant_entertain_ng"].allowed_roles) == {"male_companion", "female_companion"}
    assert set(ORDER_RULES["lol_entertain_ng"].allowed_roles) == {"male_companion", "female_companion"}


def test_buy_8_get_1_and_prices():
    rule = ORDER_RULES["valorant_radiant_ranked"]
    result = calculate_price(rule, quantity=8, player_count=2)
    assert rule.price == 700
    assert result.base_amount == 11200
    assert result.service_quantity == 9
    assert set(get_allowed_role_ids(rule)) == {"1545357782906314782"}

    lol = ORDER_RULES["lol_entertain_aram"]
    assert lol.price == 350
    assert lol.unit_label == "H"
    assert calculate_price(lol, quantity=8, player_count=1).service_quantity == 9
