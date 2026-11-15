from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from services import order_rules
from services import orders
from services.order_rules import (
    OrderRule,
    ORDER_RULES,
    ALL_RECEIVER_ROLES,
    PROTECTOR_ROLES,
    build_custom_rule,
    build_rule_with_override,
    calculate_price,
    get_base_rule,
    get_required_staff_count,
    rule_to_override_payload,
    validate_rule_definition,
)
from web.app.routers.admin_order_rules import _apply_fun_free_specify_policy
from services import quick_order_v2_price_lists as price_lists


ROOT = Path(__file__).resolve().parents[1]


def _active_fun_keys() -> set[str]:
    return {
        str(detail["rule_key"])
        for group in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]
        for detail in group["details"]
    }


@pytest.mark.parametrize("key", sorted(_active_fun_keys()))
def test_all_live_fun_skus_allow_zero_fee_designation_without_changing_price_or_headcount(key):
    rule = get_base_rule(key)
    assert rule.category == "delta_desktop_fun"
    assert rule.allow_specify is True
    assert rule.specify_fee_default == 0
    assert rule.specify_free_min_units is None
    assert rule.specify_fee_by_role == {role: 0 for role in rule.allowed_roles}
    assert rule.specify_fee_by_game_role == {role: 0 for role in rule.allowed_game_roles}
    assert rule.max_specified_count == get_required_staff_count(rule)

    original_price = calculate_price(rule, quantity=1)
    role = (tuple(rule.allowed_roles) + tuple(rule.allowed_game_roles))[0]
    specified_price = calculate_price(rule, quantity=1, specified_roles=[role])
    assert specified_price.specify_fee == 0
    assert specified_price.total_amount == original_price.total_amount
    assert specified_price.base_amount == original_price.base_amount
    assert specified_price.required_staff_count == original_price.required_staff_count
    validate_rule_definition(key, rule)


def test_two_specified_staff_are_free_and_original_claim_qualifications_remain_intact():
    for key, expected_roles, protectors_required in (
        ("fun_lovebirds", ALL_RECEIVER_ROLES, 1),
        ("fun_read_no_reply", ALL_RECEIVER_ROLES, 1),
        ("fun_rich_enough", PROTECTOR_ROLES, 0),
        ("fun_eat_yourself", PROTECTOR_ROLES, 0),
        ("fun_eat_to_fat_10kg", ALL_RECEIVER_ROLES, 0),
        ("fun_our_love_start_50", PROTECTOR_ROLES, 2),
        ("fun_mawan_galagame_basic", ("female_companion", "female_protector"), 0),
    ):
        rule = get_base_rule(key)
        assert rule.allowed_roles == expected_roles
        assert rule.min_protector_count == protectors_required
        assert rule.required_staff_count == 2
        assert rule.max_specified_count == 2
        for role in rule.allowed_roles:
            price = calculate_price(rule, specified_roles=[role], quantity=1)
            assert price.specify_fee == 0
            assert price.total_amount == rule.price

        both = calculate_price(rule, specified_roles=rule.allowed_roles[:2], quantity=1)
        assert both.specify_fee == 0
        assert both.total_amount == rule.price

    # Being able to specify is NOT permission to select an ineligible role.
    with pytest.raises(ValueError, match="不能接"):
        calculate_price(
            get_base_rule("fun_our_love_start_50"),
            quantity=1,
            specified_roles=["male_companion"],
        )


def test_future_custom_fun_rule_also_gets_free_designation_without_role_expansion():
    seed = OrderRule(
        category="delta_desktop_fun",
        key="admin_fun_free",
        label="管理員新增趣味單",
        pricing_type="fixed",
        price=3211,
        allowed_roles=("female_protector",),
        required_game_roles=("delta_desktop",),
        required_staff_count=2,
        max_specified_count=None,
        allow_specify=False,
        specify_fee_default=100,
        specify_fee_by_role={"female_protector": 300},
    )
    custom = build_custom_rule(seed.key, seed.category, rule_to_override_payload(seed))
    assert custom.allowed_roles == seed.allowed_roles
    assert custom.required_game_roles == seed.required_game_roles
    assert custom.allow_specify
    assert custom.max_specified_count == 2
    assert custom.specify_fee_by_role == {"female_protector": 0}
    assert custom.specify_fee_default == 0
    assert calculate_price(custom, specified_roles=["female_protector"], quantity=1).total_amount == 3211


def test_existing_and_approved_manager_overrides_cannot_reintroduce_fun_designation_fees(monkeypatch):
    key = "fun_rich_enough"
    base = get_base_rule(key)
    malicious = rule_to_override_payload(base)
    malicious.update(
        allow_specify=False,
        max_specified_count=1,
        specify_fee_default=800,
        specify_fee_by_role={role: 800 for role in base.allowed_roles},
    )
    for confirmed in (False, True):
        payload = dict(malicious)
        if confirmed:
            payload["__owner_confirmed_after_canonical"] = True
        monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
        monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": payload}})
        effective = ORDER_RULES[key]
        assert effective.allow_specify
        assert effective.max_specified_count == 2
        assert effective.specify_fee_default == 0
        assert calculate_price(effective, specified_roles=["top_protector"], quantity=1).specify_fee == 0
        assert effective.price == base.price


def test_manager_fun_form_forces_zero_fee_and_designation_even_if_unchecked():
    payload = {
        "allowed_roles": ["female_companion", "female_protector"],
        "allowed_game_roles": [],
        "allow_specify": False,
        "required_staff_count": 2,
        "max_specified_count": 1,
        "specify_fee_default": 100,
        "specify_fee_by_role": {"female_companion": 800},
        "specify_free_min_units": 2,
    }
    normalized = _apply_fun_free_specify_policy("delta_desktop_fun", payload)
    assert normalized["allow_specify"] is True
    assert normalized["max_specified_count"] == 2
    assert normalized["specify_fee_default"] == 0
    assert normalized["specify_fee_by_role"] == {
        "female_companion": 0, "female_protector": 0
    }
    assert normalized["specify_free_min_units"] is None
    assert normalized["allowed_roles"] == payload["allowed_roles"]

    ordinary = _apply_fun_free_specify_policy("delta_desktop_basic", payload)
    assert ordinary["allow_specify"] is False
    assert ordinary["specify_fee_default"] == 100


def test_all_live_fun_rules_are_reflected_in_discord_and_web_without_a_second_fee():
    from web.app.services import order_catalog_cards

    cards = order_catalog_cards._build_cards("delta_desktop_fun")
    all_fun_keys = _active_fun_keys()
    seen = set()
    for card in cards:
        detail = order_catalog_cards._build_group_detail(card["key"])
        if not detail:
            continue
        for variant in detail["variants"]:
            key = str(variant["rule_key"])
            if key not in all_fun_keys:
                continue
            seen.add(key)
            assert variant["allow_specify"] is True
            assert variant["max_specified_count"] == 2
    assert seen == all_fun_keys

    for plan_key in price_lists.DELTA_FUN_PRICE_LISTS:
        embed = price_lists._delta_fun_embed(plan_key)
        assert "指定費 0T" in str(embed.footer.text)


def test_discord_ticket_copy_identifies_fun_free_designation():
    source = (ROOT / "services/self_service_ui_runtime.py").read_text(encoding="utf-8")
    assert "趣味單全品項開放免費指定（0T）" in source


def test_no_legacy_quick_ticket_patch_to_stack_on_production():
    quick_source = (ROOT / "services/quick_order_v2.py").read_text(encoding="utf-8")
    fix_source = (ROOT / "services/quick_order_v2_fixes.py").read_text(encoding="utf-8")
    production = (ROOT / "services/quick_order_v2_production.py").read_text(encoding="utf-8")
    assert "def _install_ticket_patch" not in quick_source
    assert "_PATCH_INSTALLED" not in quick_source
    assert "def _disable_legacy_ticket_patch" not in fix_source
    assert production.count("ui.SelfServiceOrderView.__init__ =") == 1
