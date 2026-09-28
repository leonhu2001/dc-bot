import services
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
from web.app.services.order_groups import get_grouped_order_catalog


def test_lol_and_apex_master_roles_never_mix():
    lol_master = GAME_ROLE_BY_KEY["lol_master"]
    apex_master = GAME_ROLE_BY_KEY["apex_master"]

    assert lol_master.game == "lol"
    assert lol_master.role_id == "1545362644607832065"

    assert apex_master.game == "apex"
    assert apex_master.role_id == "1545364180905885746"

    assert lol_master.role_id != apex_master.role_id


def test_delta_force_protectors_are_registered_as_game_roles():
    expected = {
        "delta_top_protector": ("1500234130871550004", "魔丸♛頂護"),
        "delta_female_protector": ("1500234170943934544", "魔丸♝女護"),
        "delta_male_protector": ("1500751039060643990", "魔丸♜男護"),
    }

    for key, (role_id, label) in expected.items():
        role = GAME_ROLE_BY_KEY[key]
        assert role.game == "delta_force"
        assert role.role_id == role_id
        assert role.label == label

    assert {
        GAME_ROLE_BY_KEY[key].role_id
        for key in expected
    } == {
        ROLE_IDS["top_protector"],
        ROLE_IDS["female_protector"],
        ROLE_IDS["male_protector"],
    }


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


def test_steam_accepts_all_five_legacy_roles_and_all_registered_game_roles():
    steam = ORDER_RULES["steam_play"]
    allowed_ids = set(get_allowed_role_ids(steam))

    assert set(steam.allowed_roles) == set(ROLE_IDS)
    assert set(steam.allowed_game_roles) == set(GAME_ROLE_BY_KEY)
    assert len(GAME_ROLE_BY_KEY) == 12
    assert allowed_ids == set(ALL_ROLE_IDS.values())
    assert len(allowed_ids) == 14


def test_apex_roles_can_login_employee_website_before_apex_orders_exist():
    for key in ("apex_predator", "apex_master", "apex_diamond"):
        role_id = GAME_ROLE_BY_KEY[key].role_id
        assert can_login_dashboard([role_id]) is True


def test_new_lol_and_valorant_orders_allow_specify_with_100t_fee_and_max_four_staff():
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
        assert rule.allow_specify is True
        assert rule.max_player_count == 4
        assert rule.point_benefits_allowed is True
        assert rule.specify_fee_default == 100
        assert all(int(value) == 100 for value in rule.specify_fee_by_role.values())
        assert all(int(value) == 100 for value in rule.specify_fee_by_game_role.values())


def test_buy_8_get_1_and_prices():
    rule = ORDER_RULES["valorant_radiant_ranked"]
    result = calculate_price(rule, quantity=8, player_count=2)
    assert rule.price == 400
    assert result.base_amount == 6400
    assert result.service_quantity == 9
    assert set(get_allowed_role_ids(rule)) == {"1545357782906314782"}

    lol = ORDER_RULES["lol_entertain_aram"]
    assert lol.price == 300
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

        # 沒有指定陪玩時，不應出現免指定費兌換。
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="free_specify_fee",
            **common,
        )["allowed"] is False



def test_game_priced_point_time_benefits_become_one_and_two_games():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="valorant_entertain_ranked",
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


def test_delta_desktop_and_mobile_pricing_are_separate():
    assert ORDER_RULES["basic_entertain_single"].price == 320
    assert ORDER_RULES["basic_entertain_double"].price == 600
    assert ORDER_RULES["basic_mobile_entertain_single"].price == 320
    assert ORDER_RULES["basic_mobile_entertain_double"].price == 600

    assert ORDER_RULES["basic_tech_secret_single"].price == 400
    assert ORDER_RULES["basic_tech_topsecret_single"].price == 450
    assert ORDER_RULES["basic_mobile_tech_secret_single"].price == 380
    assert ORDER_RULES["basic_mobile_tech_topsecret_single"].price == 420
    assert ORDER_RULES["basic_exbar_tech"].price == 1000
    assert ORDER_RULES["basic_exbar_tech"].note == "保底三選一：800w / 500w + 2 沙色保險 / 4 沙色保險"

    assert not hasattr(services, "_RULE_UPDATES")

    assert ORDER_RULES["basic_tech_secret_double"].price == 750
    assert ORDER_RULES["basic_tech_topsecret_double"].price == 850
    assert ORDER_RULES["basic_mobile_tech_secret_double"].price == 760
    assert ORDER_RULES["basic_mobile_tech_topsecret_double"].price == 840


def test_delta_platform_labels_survive_runtime_overrides():
    expected = {
        "basic_tech_secret_single": "技術陪〈端遊〉｜機密單陪",
        "basic_tech_secret_double": "技術陪〈端遊〉｜機密雙陪",
        "basic_tech_topsecret_single": "技術陪〈端遊〉｜絕密單陪",
        "basic_tech_topsecret_double": "技術陪〈端遊〉｜絕密雙陪",
        "basic_mobile_tech_secret_single": "技術陪〈手遊〉｜機密單陪",
        "basic_mobile_tech_secret_double": "技術陪〈手遊〉｜機密雙陪",
        "basic_mobile_tech_topsecret_single": "技術陪〈手遊〉｜絕密單陪",
        "basic_mobile_tech_topsecret_double": "技術陪〈手遊〉｜絕密雙陪",
        "basic_entertain_single": "娛樂陪〈端遊〉｜單陪",
        "basic_entertain_double": "娛樂陪〈端遊〉｜雙陪",
        "basic_mobile_entertain_single": "娛樂陪〈手遊〉｜單陪",
        "basic_mobile_entertain_double": "娛樂陪〈手遊〉｜雙陪",
    }
    for key, label in expected.items():
        rule = ORDER_RULES[key]
        assert rule.label == label, key
        assert rule.min_quantity == 1, key
        assert rule.max_quantity == 24, key


def test_all_season_3x3_variants_allow_all_five_store_roles():
    keys = (
        "farm_season_3x3_normal",
        "farm_season_3x3_skin",
        "farm_season_3x3_dc_skin",
        "farm_season_3x3_dc_loss",
        "farm_season_3x3_dc_skin_loss",
    )
    expected = set(ROLE_IDS)
    for key in keys:
        assert set(ORDER_RULES[key].allowed_roles) == expected, key

    # 命運契約不是 3x3，本次不放寬。
    assert set(ORDER_RULES["farm_season_3x3_contract"].allowed_roles) != expected



def test_web_delta_catalog_exposes_desktop_and_mobile_groups():
    groups = {
        group["key"]: group
        for group in get_grouped_order_catalog("basic")
    }

    assert groups["tech_play"]["label"] == "技術陪〈端遊〉"
    assert groups["tech_play_mobile"]["label"] == "技術陪〈手遊〉"
    assert groups["entertain"]["label"] == "娛樂陪〈端遊〉"
    assert groups["entertain_mobile"]["label"] == "娛樂陪〈手遊〉"

    assert [variant["rule_key"] for variant in groups["tech_play_mobile"]["variants"]] == [
        "basic_mobile_tech_secret_single",
        "basic_mobile_tech_secret_double",
        "basic_mobile_tech_topsecret_single",
        "basic_mobile_tech_topsecret_double",
    ]
    assert [variant["price"] for variant in groups["tech_play_mobile"]["variants"]] == [
        380,
        760,
        420,
        840,
    ]
    assert [variant["rule_key"] for variant in groups["entertain_mobile"]["variants"]] == [
        "basic_mobile_entertain_single",
        "basic_mobile_entertain_double",
    ]
    assert [variant["price"] for variant in groups["entertain_mobile"]["variants"]] == [
        320,
        600,
    ]



def test_storefront_business_values_are_direct_rules():
    expected = {
        "basic_sweet_single": ("hourly", 520, "H"),
        "basic_sweet_double": ("hourly", 1314, "H"),
        "basic_trial_500": ("fixed", 450, "單"),
        "basic_trial_1000": ("fixed", 900, "單"),
        "basic_bet_1000": ("fixed", 800, "單"),
        "basic_bet_1500": ("fixed", 1200, "單"),
        "basic_bet_2500": ("fixed", 1500, "單"),
        "basic_oil_fuel": ("fixed", 2600, "單"),
        "basic_oil_satellite": ("fixed", 1800, "單"),
        "basic_oil_all": ("fixed", 4000, "單"),
        "steam_play": ("hourly", 320, "H"),

        "valorant_entertain_ng": ("hourly", 300, "H"),
        "valorant_entertain_ranked": ("game", 250, "局"),
        "valorant_ascendant_ng": ("hourly", 340, "H"),
        "valorant_ascendant_ranked": ("game", 300, "局"),
        "valorant_immortal_ng": ("hourly", 360, "H"),
        "valorant_immortal_ranked": ("game", 350, "局"),
        "valorant_radiant_ng": ("hourly", 400, "H"),
        "valorant_radiant_ranked": ("game", 400, "局"),

        "lol_entertain_aram": ("hourly", 300, "H"),
        "lol_entertain_ng": ("hourly", 300, "H"),
        "lol_entertain_ranked": ("game", 250, "局"),
        "lol_master_ng": ("hourly", 340, "H"),
        "lol_master_ranked": ("game", 300, "局"),
        "lol_grandmaster_ng": ("hourly", 360, "H"),
        "lol_grandmaster_ranked": ("game", 350, "局"),
        "lol_elite_ng": ("hourly", 400, "H"),
        "lol_elite_ranked": ("game", 400, "局"),

        "apex_entertain_platinum": ("hourly", 300, "H"),
        "apex_entertain_platinum_ranked": ("hourly", 350, "H"),
        "apex_entertain_diamond": ("hourly", 330, "H"),
        "apex_entertain_diamond_ranked": ("hourly", 380, "H"),
        "apex_entertain_master": ("hourly", 350, "H"),
        "apex_entertain_master_ranked": ("hourly", 400, "H"),
        "apex_diamond_platinum": ("hourly", 360, "H"),
        "apex_diamond_platinum_ranked": ("hourly", 410, "H"),
        "apex_diamond_diamond": ("hourly", 400, "H"),
        "apex_diamond_diamond_ranked": ("hourly", 450, "H"),
        "apex_master_platinum": ("hourly", 420, "H"),
        "apex_master_platinum_ranked": ("hourly", 470, "H"),
        "apex_master_diamond": ("hourly", 460, "H"),
        "apex_master_diamond_ranked": ("hourly", 510, "H"),
        "apex_master_master": ("hourly", 500, "H"),
        "apex_master_master_ranked": ("hourly", 550, "H"),
        "apex_predator_platinum": ("hourly", 500, "H"),
        "apex_predator_platinum_ranked": ("hourly", 550, "H"),
        "apex_predator_diamond": ("hourly", 550, "H"),
        "apex_predator_diamond_ranked": ("hourly", 600, "H"),
        "apex_predator_master": ("hourly", 600, "H"),
        "apex_predator_master_ranked": ("hourly", 650, "H"),
    }

    for key, (pricing_type, price, unit_label) in expected.items():
        rule = ORDER_RULES[key]
        assert rule.pricing_type == pricing_type, key
        assert rule.price == price, key
        assert rule.unit_label == unit_label, key


def test_no_current_rule_uses_old_150_specify_fee():
    for key, rule in ORDER_RULES.items():
        assert int(rule.specify_fee_default or 0) != 150, key
        assert 150 not in {
            int(value or 0)
            for value in (rule.specify_fee_by_role or {}).values()
        }, key
        assert 150 not in {
            int(value or 0)
            for value in (rule.specify_fee_by_game_role or {}).values()
        }, key
