from services.game_roles import GAME_ROLE_BY_KEY
from services.order_rules import (
    ALL_ROLE_IDS,
    ORDER_RULES,
    ROLE_IDS,
    calculate_price,
    get_allowed_role_ids,
    get_allowed_role_keys,
)
from web.app.services.checkout_preview import (
    list_point_options,
    point_item_status,
)
from web.app.services.role_catalog import can_login_dashboard


def test_lol_and_apex_master_roles_never_mix():
    lol_master = GAME_ROLE_BY_KEY["lol_master"]
    apex_master = GAME_ROLE_BY_KEY["apex_master"]

    assert lol_master.game == "lol"
    assert lol_master.role_id == "1545362644607832065"

    assert apex_master.game == "apex"
    assert apex_master.role_id == "1545364180905885746"

    assert lol_master.role_id != apex_master.role_id


def test_game_rank_orders_do_not_inherit_delta_protector_roles():
    assert ORDER_RULES["valorant_ascendant_ng"].allowed_roles == ()
    assert ORDER_RULES["lol_master_ng"].allowed_roles == ()
    assert ORDER_RULES["valorant_ascendant_ng"].allowed_game_roles == (
        "valorant_ascendant",
        "valorant_immortal",
        "valorant_radiant",
    )
    assert ORDER_RULES["lol_master_ng"].allowed_game_roles == (
        "lol_master",
        "lol_grandmaster",
        "lol_elite",
    )


def test_entertainment_uses_universal_companions_plus_same_game_ranks():
    valorant = ORDER_RULES["valorant_entertain_ng"]
    lol = ORDER_RULES["lol_entertain_ng"]

    assert set(valorant.allowed_roles) == {"male_companion", "female_companion"}
    assert set(lol.allowed_roles) == {"male_companion", "female_companion"}

    assert set(valorant.allowed_game_roles) == {
        "valorant_ascendant",
        "valorant_immortal",
        "valorant_radiant",
    }
    assert set(lol.allowed_game_roles) == {
        "lol_master",
        "lol_grandmaster",
        "lol_elite",
    }


def test_steam_accepts_all_five_legacy_roles_and_all_nine_game_ranks():
    steam = ORDER_RULES["steam_play"]
    allowed_ids = set(get_allowed_role_ids(steam))

    assert set(steam.allowed_roles) == set(ROLE_IDS)
    assert set(steam.allowed_game_roles) == set(GAME_ROLE_BY_KEY)
    assert allowed_ids == set(ALL_ROLE_IDS.values())
    assert len(allowed_ids) == 14


def test_apex_roles_can_login_employee_website_before_apex_orders_exist():
    for key in ("apex_predator", "apex_master", "apex_diamond"):
        role_id = GAME_ROLE_BY_KEY[key].role_id
        assert can_login_dashboard([role_id]) is True


def test_new_lol_and_valorant_orders_cannot_specify_and_max_four_staff():
    keys = [
        "valorant_entertain_ng",
        "valorant_entertain_ranked",
        "valorant_ascendant_ng",
        "valorant_ascendant_ranked",
        "valorant_immortal_ng",
        "valorant_immortal_ranked",
        "valorant_radiant_ng",
        "valorant_radiant_ranked",
        "lol_entertain_aram",
        "lol_entertain_ng",
        "lol_entertain_ranked",
        "lol_master_ng",
        "lol_master_ranked",
        "lol_grandmaster_ng",
        "lol_grandmaster_ranked",
        "lol_elite_ng",
        "lol_elite_ranked",
    ]

    for key in keys:
        rule = ORDER_RULES[key]
        assert rule.allow_specify is False
        assert rule.max_player_count == 4
        assert rule.point_benefits_allowed is True


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


def test_new_game_orders_allow_points_except_extra_game_and_unusable_specify_fee():
    common = dict(point_balance=999, quantity=1, has_specified_staff=False)

    for rule_key in ("valorant_entertain_ng", "lol_entertain_ng"):
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="discount_20",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="extra_10",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="extra_15",
            **common,
        )["allowed"] is False

        # 商品目前不開放指定，不能讓客人浪費點數換免指定費。
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="free_specify_fee",
            **common,
        )["allowed"] is False



def test_game_priced_point_time_benefits_become_one_and_two_games():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="valorant_entertain_ng",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    assert options["extra_10"]["allowed"] is True
    assert options["extra_10"]["name"] == "加一局"
    assert options["extra_10"]["kind"] == "extra_games"
    assert options["extra_10"]["games"] == 1

    assert options["extra_30"]["allowed"] is True
    assert options["extra_30"]["name"] == "加兩局"
    assert options["extra_30"]["kind"] == "extra_games"
    assert options["extra_30"]["games"] == 2

    # 原本的「加場一場保撤」仍然不適用特戰英豪 / 英雄聯盟。
    assert options["extra_15"]["allowed"] is False


def test_hourly_point_time_benefits_keep_original_time_units():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="lol_entertain_aram",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    assert options["extra_10"]["name"] == "加時 30 分鐘"
    assert options["extra_10"]["kind"] == "extra_hours"
    assert options["extra_10"]["hours"] == 0.5

    assert options["extra_30"]["name"] == "加時 1 小時"
    assert options["extra_30"]["kind"] == "extra_hours"
    assert options["extra_30"]["hours"] == 1


def test_all_new_game_orders_have_exact_receiver_roles():
    expected = {
        "valorant_entertain_ng": (
            "male_companion",
            "female_companion",
            "valorant_ascendant",
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_entertain_ranked": (
            "male_companion",
            "female_companion",
            "valorant_ascendant",
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_ascendant_ng": (
            "valorant_ascendant",
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_ascendant_ranked": (
            "valorant_ascendant",
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_immortal_ng": (
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_immortal_ranked": (
            "valorant_immortal",
            "valorant_radiant",
        ),
        "valorant_radiant_ng": (
            "valorant_radiant",
        ),
        "valorant_radiant_ranked": (
            "valorant_radiant",
        ),
        "lol_entertain_aram": (
            "male_companion",
            "female_companion",
            "lol_master",
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_entertain_ng": (
            "male_companion",
            "female_companion",
            "lol_master",
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_entertain_ranked": (
            "male_companion",
            "female_companion",
            "lol_master",
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_master_ng": (
            "lol_master",
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_master_ranked": (
            "lol_master",
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_grandmaster_ng": (
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_grandmaster_ranked": (
            "lol_grandmaster",
            "lol_elite",
        ),
        "lol_elite_ng": (
            "lol_elite",
        ),
        "lol_elite_ranked": (
            "lol_elite",
        ),
    }

    for rule_key, expected_keys in expected.items():
        actual_keys = get_allowed_role_keys(ORDER_RULES[rule_key])
        assert actual_keys == expected_keys, rule_key

        # LOL / 特戰英豪 orders must never inherit any APEX rank.
        assert not any(
            role_key.startswith("apex_")
            for role_key in actual_keys
        ), rule_key
