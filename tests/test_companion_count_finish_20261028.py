from __future__ import annotations

from types import SimpleNamespace

import services  # noqa: F401 - installs production migrations under test
from services import order_rules, orders
from services.multi_seat_order_policy_20261028 import (
    PLAYER_COUNT_PRICE_TABLES,
    get_rule_player_count_bounds,
)
from services.order_rule_store import (
    get_active_override,
    publish_rule_override,
    rollback_rule_override,
)
from services.sweet_companion_policy_20261028 import (
    SWEET_COMPANION_ROLE_ID,
    SWEET_COMPANION_ROLE_KEY,
)


def _details(category: str, group: str) -> list[dict]:
    return orders.get_order_item_details_for_group(category, group)


def test_delta_technical_shared_catalog_is_count_neutral_and_keeps_stable_values() -> None:
    desktop = _details("delta_desktop_basic", "技術陪")
    mobile = _details("delta_mobile_basic", "技術陪")

    assert [item["label"] for item in desktop] == ["機密", "絕密"]
    assert [item["value"] for item in desktop] == ["secret_single", "topsecret_single"]
    assert [item["rule_key"] for item in desktop] == [
        "basic_tech_secret_single",
        "basic_tech_topsecret_single",
    ]

    assert [item["label"] for item in mobile] == ["機密", "絕密"]
    assert [item["value"] for item in mobile] == [
        "mobile_secret_single",
        "mobile_topsecret_single",
    ]
    assert [item["rule_key"] for item in mobile] == [
        "basic_mobile_tech_secret_single",
        "basic_mobile_tech_topsecret_single",
    ]
    assert all("player_count" not in item for item in desktop + mobile)


def test_existing_quick_ticket_value_resolves_and_unlocks_companion_count() -> None:
    detail = orders.get_order_item_detail_for_selection(
        "delta_desktop_basic",
        "技術陪",
        "secret_single",
    )
    assert detail is not None
    assert detail["label"] == "機密"
    assert detail["rule_key"] == "basic_tech_secret_single"

    rule = order_rules.ORDER_RULES[detail["rule_key"]]
    assert get_rule_player_count_bounds(rule) == (1, 2, 1, True)
    assert rule.required_staff_count == "player_count"
    assert rule.player_count_enabled is True
    assert rule.catalog_group_label == ""


def test_delta_technical_rules_are_direct_base_rules_not_read_time_wrappers() -> None:
    for key in (
        "basic_tech_secret_single",
        "basic_tech_topsecret_single",
        "basic_mobile_tech_secret_single",
        "basic_mobile_tech_topsecret_single",
    ):
        base = order_rules.get_base_rule(key)
        assert base.required_staff_count == "player_count"
        assert base.player_count_enabled is True
        assert base.min_player_count == 1
        assert base.max_player_count == 2
        assert base.max_specified_count == 2
        assert base.catalog_group_label == ""

    assert not getattr(
        order_rules.ORDER_RULES,
        "_multi_seat_effective_rule_runtime_installed",
        False,
    )
    assert not getattr(
        order_rules.ORDER_RULES,
        "_companion_count_catalog_cleanup_installed",
        False,
    )

    # Old fixed-double rules stay available only for historical snapshots/orders.
    assert order_rules.ORDER_RULES["basic_tech_secret_double"].required_staff_count == 2
    assert order_rules.ORDER_RULES["basic_mobile_tech_secret_double"].required_staff_count == 2


def test_delta_technical_two_companion_prices_are_preserved() -> None:
    cases = {
        "basic_tech_secret_single": 750,
        "basic_tech_topsecret_single": 850,
        "basic_mobile_tech_secret_single": 760,
        "basic_mobile_tech_topsecret_single": 840,
    }
    for key, expected in cases.items():
        assert PLAYER_COUNT_PRICE_TABLES[key][2] == expected
        result = order_rules.calculate_price(
            order_rules.ORDER_RULES[key],
            quantity=1,
            player_count=2,
        )
        assert result.base_amount == expected
        assert result.required_staff_count == 2


def test_delta_entertainment_uses_type_plus_independent_count_without_web_rename() -> None:
    for key in (
        "basic_entertain_single",
        "basic_entertain_female_single",
        "basic_entertain_male_single",
        "basic_mobile_entertain_single",
        "basic_mobile_entertain_female_single",
        "basic_mobile_entertain_male_single",
    ):
        rule = order_rules.ORDER_RULES[key]
        assert get_rule_player_count_bounds(rule) == (1, 2, 1, True)
        assert PLAYER_COUNT_PRICE_TABLES[key] == {1: 320, 2: 600}
        assert rule.catalog_group_label == ""


def test_stale_admin_override_is_canonicalized_when_written(tmp_path) -> None:
    db_file = tmp_path / "rules.db"
    stale = order_rules.rule_to_override_payload(
        order_rules.get_base_rule("basic_tech_secret_single")
    )
    stale.update({
        "label": "機密｜單陪",
        "catalog_group_label": "技術陪",
        "required_staff_count": 1,
        "player_count_enabled": False,
        "min_player_count": 1,
        "max_player_count": 1,
        "max_specified_count": 1,
        "price_multiply_player_count": False,
    })

    saved = publish_rule_override(
        rule_key="basic_tech_secret_single",
        payload=stale,
        actor_discord_id="test",
        actor_display_name="test",
        db_file=db_file,
    )
    payload = saved["payload"]
    assert payload["required_staff_count"] == "player_count"
    assert payload["player_count_enabled"] is True
    assert payload["max_player_count"] == 2
    assert payload["max_specified_count"] == 2
    assert payload["catalog_group_label"] == ""
    assert payload["required_game_roles"] == ["delta_desktop"]

    # Even rolling back a deliberately old structural version cannot resurrect the
    # fixed-single rule because rollback goes through the same write boundary.
    rolled = rollback_rule_override(
        rule_key="basic_tech_secret_single",
        target_version=1,
        actor_discord_id="test",
        actor_display_name="test",
        expected_active_version=1,
        db_file=db_file,
    )
    assert rolled["payload"]["required_staff_count"] == "player_count"
    assert rolled["payload"]["max_player_count"] == 2
    assert rolled["payload"]["catalog_group_label"] == ""

    active = get_active_override("basic_tech_secret_single", db_file)
    assert active is not None
    assert active["payload"]["required_staff_count"] == "player_count"


def test_sweet_shared_catalog_uses_gender_type_plus_independent_count() -> None:
    prefixes = {
        "delta_desktop_basic": "delta_desktop",
        "delta_mobile_basic": "delta_mobile",
        "steam": "steam",
        "valorant": "valorant",
        "lol": "lol",
        "apex": "apex",
    }

    for category, prefix in prefixes.items():
        details = _details(category, "甜蜜單")
        assert [item["label"] for item in details] == ["女陪", "男陪", "不限"]
        assert [item["value"] for item in details] == ["female_single", "male_single", "any"]
        assert [item["rule_key"] for item in details] == [
            f"{prefix}_sweet_female",
            f"{prefix}_sweet_male",
            f"{prefix}_sweet_any",
        ]

        for item in details:
            rule = order_rules.ORDER_RULES[item["rule_key"]]
            base = order_rules.get_base_rule(item["rule_key"])
            assert rule.required_staff_count == "player_count"
            assert rule.player_count_enabled is True
            assert rule.min_player_count == 1
            assert rule.max_player_count == 2
            assert base.required_staff_count == "player_count"
            assert PLAYER_COUNT_PRICE_TABLES[item["rule_key"]] == {1: 520, 2: 1314}

        assert order_rules.ORDER_RULES[f"{prefix}_sweet_female_single"].required_staff_count == 1
        assert order_rules.ORDER_RULES[f"{prefix}_sweet_female_double"].required_staff_count == 2
        assert order_rules.ORDER_RULES[f"{prefix}_sweet_male_double"].required_staff_count == 2


def test_sweet_override_always_keeps_game_identity_and_sweet_role(tmp_path) -> None:
    key = "valorant_sweet_female"
    stale = order_rules.rule_to_override_payload(order_rules.get_base_rule(key))
    stale.update({
        "catalog_group_label": "甜蜜單",
        "required_staff_count": 1,
        "player_count_enabled": False,
        "max_player_count": 1,
        "required_game_roles": ["valorant_game"],
    })
    saved = publish_rule_override(
        rule_key=key,
        payload=stale,
        actor_discord_id="test",
        actor_display_name="test",
        db_file=tmp_path / "sweet.db",
    )
    assert saved["payload"]["required_staff_count"] == "player_count"
    assert saved["payload"]["max_player_count"] == 2
    assert saved["payload"]["required_game_roles"] == [
        "valorant_game",
        SWEET_COMPANION_ROLE_KEY,
    ]


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
        [female_role_id, *game_ids], allowed, required
    ) is False
    assert order_rules.role_ids_match_requirements(
        [female_role_id, SWEET_COMPANION_ROLE_ID], allowed, required
    ) is False
    assert order_rules.role_ids_match_requirements(
        [female_role_id, SWEET_COMPANION_ROLE_ID, game_ids[0]], allowed, required
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


def test_legacy_sweet_rules_do_not_gain_new_requirement() -> None:
    legacy_general = order_rules.ORDER_RULES["basic_sweet_female_single"]
    old_game_rule = order_rules.ORDER_RULES["valorant_sweet_female_single"]
    assert order_rules.get_required_game_role_keys(legacy_general) == ()
    assert order_rules.get_required_game_role_keys(old_game_rule) == ("valorant_game",)
    assert SWEET_COMPANION_ROLE_ID not in order_rules.get_required_game_role_ids(old_game_rule)
    assert not getattr(order_rules.ORDER_RULES, "_sweet_companion_policy_installed", False)


def test_quick_order_notice_installed_without_replacing_locked_ticket_patch() -> None:
    from services import quick_order_v2 as quick

    assert quick._order_notice_confirmation_installed is True
    assert quick._send_confirmation.__module__ == "services.quick_order_ticket_policy_20261028"
    assert quick._install_ticket_patch.__module__ == "services.quick_order_v2"
    assert not getattr(quick, "_unified_ticket_patch_wrapper_installed", False)
