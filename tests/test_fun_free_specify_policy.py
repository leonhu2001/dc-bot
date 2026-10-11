import pytest

from services.order_rules import (
    calculate_price,
    get_base_rule,
    preview_rule_override,
    rule_to_override_payload,
)
from web.app.routers.admin_order_rules import _apply_fun_free_specify_policy


def test_fun_order_can_publish_with_zero_specify_fee():
    key = "fun_read_no_reply"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["allow_specify"] = True
    payload["max_specified_count"] = 2
    payload["specify_fee_default"] = 0
    payload["specify_fee_by_role"] = {}
    payload["specify_fee_by_game_role"] = {}

    normalized = _apply_fun_free_specify_policy("delta_desktop_fun", payload)

    assert all(
        normalized["specify_fee_by_role"].get(role_key) == 0
        for role_key in normalized["allowed_roles"]
    )

    rule = preview_rule_override(key, normalized)
    result = calculate_price(
        rule,
        quantity=1,
        specified_roles=["top_protector", "female_protector"],
    )

    assert result.specify_fee == 0
    assert result.total_amount == result.base_amount


def test_fun_order_keeps_explicit_paid_role_fee_and_fills_only_missing_roles():
    key = "fun_read_no_reply"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["allow_specify"] = True
    payload["max_specified_count"] = 2
    payload["specify_fee_default"] = 0
    payload["specify_fee_by_role"] = {"top_protector": 100}

    normalized = _apply_fun_free_specify_policy("delta_desktop_fun", payload)

    assert normalized["specify_fee_by_role"]["top_protector"] == 100
    assert normalized["specify_fee_by_role"]["female_protector"] == 0
    assert normalized["specify_fee_by_role"]["male_protector"] == 0


def test_non_fun_order_still_blocks_missing_specify_fee():
    key = "basic_tech_secret_single"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["allow_specify"] = True
    payload["specify_fee_default"] = 0
    payload["specify_fee_by_role"] = {}
    payload["specify_fee_by_game_role"] = {}

    normalized = _apply_fun_free_specify_policy("delta_desktop_basic", payload)

    assert normalized["specify_fee_by_role"] == {}
    with pytest.raises(RuntimeError, match="specify fee missing"):
        preview_rule_override(key, normalized)
