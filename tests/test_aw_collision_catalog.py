import pytest

from services import orders
from services.aw_collision_catalog import (
    AW_GROUP_LABEL,
    AW_RULE_KEYS,
    CREDENTIAL_NOTE_PLACEHOLDER,
    aw_collision_original_amount,
    validate_aw_quantity_for_rule,
)
from services.order_credential_runtime import OrderCredentialModal
from services.order_rules import ORDER_RULES, calculate_price


def test_aw_catalog_is_under_tw_farm_category():
    assert orders.ORDER_CATEGORY_LABELS["farm"] == "台服代肝代解"
    groups = orders.SELF_SERVICE_ORDER_CATALOG["farm"]
    aw_group = next(group for group in groups if group["label"] == AW_GROUP_LABEL)
    assert [detail["rule_key"] for detail in aw_group["details"]] == list(AW_RULE_KEYS)
    assert [detail["label"] for detail in aw_group["details"]] == [
        "1～100發｜5T/發",
        "101～500發｜4.5T/發",
        "501發以上｜4T/發",
    ]
    assert all(detail["quantity_input_mode"] == "modal" for detail in aw_group["details"])


def test_aw_plan_ranges_reject_mismatched_quantity():
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[0], 100)["rate_text"] == "5"
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[1], 101)["rate_text"] == "4.5"
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[2], 501)["rate_text"] == "4"

    with pytest.raises(ValueError, match="第三欄更換方案"):
        validate_aw_quantity_for_rule(AW_RULE_KEYS[0], 101)
    with pytest.raises(ValueError, match="第三欄更換方案"):
        validate_aw_quantity_for_rule(AW_RULE_KEYS[1], 501)
    with pytest.raises(ValueError, match="第三欄更換方案"):
        validate_aw_quantity_for_rule(AW_RULE_KEYS[2], 500)


def test_aw_price_tiers_and_half_t_rounding():
    cases = [
        (AW_RULE_KEYS[0], 1, 5),
        (AW_RULE_KEYS[0], 100, 500),
        (AW_RULE_KEYS[1], 101, 455),
        (AW_RULE_KEYS[1], 200, 900),
        (AW_RULE_KEYS[1], 500, 2250),
        (AW_RULE_KEYS[2], 501, 2004),
    ]
    for rule_key, quantity, expected in cases:
        rule = ORDER_RULES[rule_key]
        result = calculate_price(rule, quantity=quantity)
        assert result.base_amount == expected
        assert result.total_amount == expected
        assert result.service_quantity == quantity
        assert aw_collision_original_amount(rule_key, quantity) == expected


def test_aw_rules_require_only_dedicated_receiver_and_no_specify():
    for key in AW_RULE_KEYS:
        rule = ORDER_RULES[key]
        assert rule.category == "farm"
        assert rule.required_staff_count == 1
        assert rule.allowed_roles == ("aw_collision_receiver",)
        assert rule.required_game_roles == ()
        assert rule.allow_specify is False


def test_credential_hint_mentions_safe_box_slots():
    assert "安全箱格數" in CREDENTIAL_NOTE_PLACEHOLDER
    modal = OrderCredentialModal(order_channel_id=123)
    assert "安全箱格數" in str(modal.login_note.placeholder or "")
