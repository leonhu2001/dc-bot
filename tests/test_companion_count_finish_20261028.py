from __future__ import annotations

from types import SimpleNamespace

import services  # noqa: F401 - installs the production policies under test
from services import order_rules
from services.sweet_companion_policy_20261028 import SWEET_COMPANION_ROLE_ID


def _discord_details(category: str, group: str) -> list[dict]:
    from services import order_runtime

    return order_runtime.get_order_item_details_for_group(category, group)


def test_delta_technical_discord_specs_use_independent_companion_count() -> None:
    desktop = _discord_details("delta_desktop_basic", "技術陪")
    mobile = _discord_details("delta_mobile_basic", "技術陪")

    assert [item["label"] for item in desktop] == ["機密", "絕密"]
    assert [item["label"] for item in mobile] == ["機密", "絕密"]
    assert all("player_count" not in item for item in desktop)
    assert all("player_count" not in item for item in mobile)

    for key in (
        "basic_tech_secret_single",
        "basic_tech_topsecret_single",
        "basic_mobile_tech_secret_single",
        "basic_mobile_tech_topsecret_single",
    ):
        rule = order_rules.ORDER_RULES[key]
        assert rule.required_staff_count == "player_count"
        assert rule.player_count_enabled is True
        assert rule.min_player_count == 1
        assert rule.max_player_count == 2

    # Historical fixed-double keys remain available for old tickets/orders.
    assert "basic_tech_secret_double" in order_rules.ORDER_RULES
    assert "basic_mobile_tech_secret_double" in order_rules.ORDER_RULES


def test_delta_technical_two_companion_prices_are_preserved() -> None:
    cases = {
        "basic_tech_secret_single": 750,
        "basic_tech_topsecret_single": 850,
        "basic_mobile_tech_secret_single": 760,
        "basic_mobile_tech_topsecret_single": 840,
    }
    for key, expected in cases.items():
        assert order_rules.get_base_rule(key).player_count_prices[2] == expected
        result = order_rules.calculate_price(
            order_rules.ORDER_RULES[key],
            quantity=1,
            player_count=2,
        )
        assert result.base_amount == expected
        assert result.required_staff_count == 2


def test_sweet_discord_specs_use_gender_type_plus_independent_count() -> None:
    prefixes = {
        "delta_desktop_basic": "delta_desktop",
        "delta_mobile_basic": "delta_mobile",
        "steam": "steam",
        "valorant": "valorant",
        "lol": "lol",
        "apex": "apex",
    }

    for category, prefix in prefixes.items():
        details = _discord_details(category, "甜蜜單")
        assert [item["label"] for item in details] == ["女陪", "男陪", "不限"]
        assert [item["rule_key"] for item in details] == [
            f"{prefix}_sweet_female",
            f"{prefix}_sweet_male",
            f"{prefix}_sweet_any",
        ]

        for item in details:
            rule = order_rules.ORDER_RULES[item["rule_key"]]
            assert rule.required_staff_count == "player_count"
            assert rule.player_count_enabled is True
            assert rule.min_player_count == 1
            assert rule.max_player_count == 2
            assert order_rules.get_base_rule(item["rule_key"]).player_count_prices == {1: 520, 2: 1314}

        # Existing fixed-seat keys remain untouched for old Web/ticket selections.
        assert order_rules.ORDER_RULES[f"{prefix}_sweet_female_single"].required_staff_count == 1
        assert order_rules.ORDER_RULES[f"{prefix}_sweet_female_double"].required_staff_count == 2
        assert order_rules.ORDER_RULES[f"{prefix}_sweet_male_double"].required_staff_count == 2


def test_sweet_price_uses_selected_companion_count() -> None:
    rule = order_rules.ORDER_RULES["valorant_sweet_female"]
    one = order_rules.calculate_price(rule, quantity=2, player_count=1)
    two = order_rules.calculate_price(rule, quantity=2, player_count=2)

    assert one.base_amount == 1040
    assert one.required_staff_count == 1
    assert two.base_amount == 2628
    assert two.required_staff_count == 2


def test_sweet_role_is_additional_and_gate() -> None:
    rule = order_rules.ORDER_RULES["valorant_sweet_female"]
    allowed = order_rules.get_allowed_role_ids(rule)
    required = order_rules.get_required_game_role_ids(rule)

    female_role_id = order_rules.ROLE_IDS["female_companion"]
    game_ids = [role_id for role_id in required if role_id != SWEET_COMPANION_ROLE_ID]

    assert SWEET_COMPANION_ROLE_ID in required
    assert game_ids

    assert order_rules.role_ids_match_requirements(
        [female_role_id, *game_ids],
        allowed,
        required,
    ) is False
    assert order_rules.role_ids_match_requirements(
        [female_role_id, SWEET_COMPANION_ROLE_ID],
        allowed,
        required,
    ) is False
    assert order_rules.role_ids_match_requirements(
        [female_role_id, SWEET_COMPANION_ROLE_ID, game_ids[0]],
        allowed,
        required,
    ) is True


def test_smart_dispatch_only_reminds_fully_qualified_sweet_workers() -> None:
    from views import smart_dispatch

    rule = order_rules.ORDER_RULES["valorant_sweet_female"]
    allowed = order_rules.get_allowed_role_ids(rule)
    required = order_rules.get_required_game_role_ids(rule)
    female_role_id = order_rules.ROLE_IDS["female_companion"]
    game_id = next(role_id for role_id in required if role_id != SWEET_COMPANION_ROLE_ID)

    def member(member_id: int, role_ids: list[str]):
        return SimpleNamespace(
            id=member_id,
            bot=False,
            roles=[SimpleNamespace(id=int(role_id)) for role_id in role_ids],
        )

    guild = SimpleNamespace(members=[
        member(1, [female_role_id, game_id]),
        member(2, [female_role_id, SWEET_COMPANION_ROLE_ID]),
        member(3, [female_role_id, game_id, SWEET_COMPANION_ROLE_ID]),
    ])

    assert smart_dispatch.get_eligible_dispatch_candidate_ids(
        guild,
        allowed_role_ids=allowed,
        required_game_role_ids=required,
    ) == ["3"]


def test_legacy_sweet_rules_do_not_gain_new_runtime_requirement() -> None:
    legacy_general = order_rules.ORDER_RULES["basic_sweet_female_single"]
    old_game_rule = order_rules.ORDER_RULES["valorant_sweet_female_single"]

    assert order_rules.get_required_game_role_keys(legacy_general) == ()
    assert order_rules.get_required_game_role_keys(old_game_rule) == ("valorant_game",)
    assert SWEET_COMPANION_ROLE_ID not in order_rules.get_required_game_role_ids(old_game_rule)


def test_quick_order_notice_installed_without_replacing_locked_ticket_patch() -> None:
    from services import quick_order_v2 as quick

    assert quick._order_notice_confirmation_installed is True
    assert quick._send_confirmation.__module__ == "services.quick_order_ticket_policy_20261028"
    assert quick._install_ticket_patch.__module__ == "services.quick_order_v2"
    assert not getattr(quick, "_unified_ticket_patch_wrapper_installed", False)


def test_delta_technical_detail_enables_quantity_after_selection() -> None:
    from services.orders import get_order_item_detail_for_selection, get_self_service_quantity_meta
    from services.self_service_selection_state import apply_self_service_detail_selection

    detail = get_order_item_detail_for_selection("delta_desktop_basic", "技術陪", "secret_single")
    assert detail is not None
    assert detail["label"] == "機密"
    data = {"category": "delta_desktop_basic", "item_group": "技術陪"}
    apply_self_service_detail_selection(data, detail)
    assert data["item"]
    assert data["order_rule_key"] == "basic_tech_secret_single"
    assert data["player_count"] == 1
    assert get_self_service_quantity_meta(
        data["category"], data["item_group"], data["item_detail_value"]
    ) == {"unit": "小時", "min": 1, "max": 24}


def test_canonical_rules_do_not_depend_on_runtime_rule_patches() -> None:
    # Base rules themselves must already have the final structure before any effective override.
    for key in (
        "basic_tech_secret_single", "basic_tech_topsecret_single",
        "basic_entertain_single", "basic_entertain_female_single", "basic_entertain_male_single",
    ):
        base = order_rules.get_base_rule(key)
        assert base.required_staff_count == "player_count"
        assert base.player_count_enabled is True
        assert base.max_player_count == 2
        assert base.player_count_prices


def test_actual_quantity_selector_is_enabled_after_delta_spec_selection(monkeypatch) -> None:
    from services import order_runtime
    from services.orders import get_order_item_detail_for_selection
    from services.self_service_selection_state import apply_self_service_detail_selection

    channel_id = 991001
    detail = get_order_item_detail_for_selection(
        "delta_desktop_basic", "技術陪", "secret_single"
    )
    assert detail is not None
    assert detail["label"] == "機密"

    data = {"category": "delta_desktop_basic", "item_group": "技術陪"}
    apply_self_service_detail_selection(data, detail)
    monkeypatch.setattr(
        order_runtime,
        "_RUNTIME_STATE",
        SimpleNamespace(order_selections={channel_id: data}),
    )

    selector = order_runtime.SelfServiceOrderQuantitySelect(
        customer_id=123,
        channel_id=channel_id,
        selected_item=data["item"],
        selected_quantity=data["quantity"],
    )
    assert selector.disabled is False
    assert selector.placeholder == "請選擇 1～24 小時"
    assert selector.options[0].value == "1"
    assert selector.options[-1].value == "24"


def test_entertainment_gender_variants_share_loyalty_progress_family() -> None:
    from services.loyalty_benefits import loyalty_scope_key

    desktop = {
        loyalty_scope_key("basic_entertain_single"),
        loyalty_scope_key("basic_entertain_female_single"),
        loyalty_scope_key("basic_entertain_male_single"),
        loyalty_scope_key("basic_entertain_double"),
    }
    mobile = {
        loyalty_scope_key("basic_mobile_entertain_single"),
        loyalty_scope_key("basic_mobile_entertain_female_single"),
        loyalty_scope_key("basic_mobile_entertain_male_single"),
        loyalty_scope_key("basic_mobile_entertain_double"),
    }
    assert len(desktop) == 1
    assert len(mobile) == 1


def test_latest_approved_game_prices_are_direct_source_values() -> None:
    expected = {
        "valorant_entertain_ng": 300,
        "valorant_entertain_ranked": 250,
        "valorant_ascendant_ng": 330,
        "valorant_ascendant_ranked": 290,
        "valorant_immortal_ng": 350,
        "valorant_immortal_ranked": 330,
        "valorant_radiant_ng": 380,
        "valorant_radiant_ranked": 370,
        "lol_master_ng": 340,
        "lol_master_ranked": 300,
        "lol_grandmaster_ng": 360,
        "lol_grandmaster_ranked": 300,
        "lol_elite_ng": 400,
        "lol_elite_ranked": 400,
        "apex_entertain_ng": 300,
        "apex_entertain_ranked": 350,
        "apex_diamond_ng": 400,
        "apex_diamond_ranked": 450,
        "apex_master_ng": 480,
        "apex_master_ranked": 530,
        "apex_predator_ng": 580,
        "apex_predator_ranked": 630,
    }
    for key, price in expected.items():
        assert order_rules.get_base_rule(key).price == price, key


def test_web_service_import_never_rewrites_authoritative_order_rules() -> None:
    from services.order_rules import get_base_rule

    expected = {
        "basic_tech_secret_single": "技術陪〈端遊〉｜機密",
        "basic_entertain_single": "娛樂陪〈端遊〉｜不限",
        "valorant_sweet_female": "特戰英豪｜甜蜜單｜女陪",
    }
    before = {key: get_base_rule(key).label for key in expected}

    import web.app.services  # noqa: F401

    after = {key: get_base_rule(key).label for key in expected}
    assert before == expected
    assert after == expected

