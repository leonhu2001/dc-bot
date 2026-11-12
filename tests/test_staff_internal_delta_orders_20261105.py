from __future__ import annotations

import pytest

from services import orders, self_service_financials
from services.aw_collision_catalog import AW_RULE_KEYS, aw_collision_original_amount, validate_aw_quantity_for_rule
from services.order_credential_runtime import OrderCredentialModal, _order_requires_credentials
from services.order_rules import (
    COIN_WASH_AW_RECEIVER_ROLE_ID,
    COIN_WASH_AW_RECEIVER_ROLES,
    ORDER_RULES,
    calculate_price,
    get_allowed_role_ids,
    rule_role_labels,
)
from services.quick_order_v2 import (
    QUICK_ORDER_V2_CHANNELS,
    QuickGameEntryView,
    build_entry_embed,
)
from services.self_service_selection_state import (
    apply_self_service_category_selection,
    apply_self_service_item_group_selection,
    apply_self_service_detail_selection,
)


INTERNAL_CATEGORY = "staff_internal"
INTERNAL_AW_RULE = "staff_internal_aw_collision"


def test_internal_panel_is_channel_scoped_and_not_in_public_category_picker():
    channel_id = 1565023979083800638
    assert QUICK_ORDER_V2_CHANNELS["staff_internal"] == channel_id
    assert INTERNAL_CATEGORY not in orders.SELF_SERVICE_ACTIVE_CATEGORIES

    view = QuickGameEntryView(category=INTERNAL_CATEGORY, source_channel_id=channel_id)
    assert len(view.children) == 1
    select = view.children[0]
    assert select.custom_id == "quick_order_v2_service_staff_internal"
    assert [option.label for option in select.options] == [
        "倒子彈｜500M",
        "撞車｜500M",
        "AW 子彈",
    ]
    panel = build_entry_embed(channel_id)
    assert "2,650T" in panel.description
    assert "2,480T" in panel.description
    assert "4T／發" in panel.description
    assert "私密表單提交登入帳密" in panel.description


@pytest.mark.parametrize(
    ("group", "rule_key", "expected"),
    [
        ("倒子彈｜500M", "staff_internal_ammo_dump_500m", 2650),
        ("撞車｜500M", "staff_internal_car_500m", 2480),
    ],
)
def test_internal_500m_coin_wash_is_one_fixed_normal_order(group, rule_key, expected):
    draft = {}
    apply_self_service_category_selection(draft, INTERNAL_CATEGORY)
    detail = apply_self_service_item_group_selection(draft, group)

    assert detail is None  # normal and priority are now separate variants
    variants = orders.get_order_item_details_for_group(INTERNAL_CATEGORY, group)
    assert len(variants) == 2
    assert variants[0]["rule_key"] == rule_key
    assert variants[1]["rule_key"] == f"{rule_key}_rush"
    apply_self_service_detail_selection(draft, variants[0])
    assert draft["order_rule_key"] == rule_key
    assert draft["quantity"] == 1
    assert _order_requires_credentials(draft) is True

    rule = ORDER_RULES[rule_key]
    assert rule.category == INTERNAL_CATEGORY
    assert rule.allowed_roles == COIN_WASH_AW_RECEIVER_ROLES
    assert get_allowed_role_ids(rule) == [COIN_WASH_AW_RECEIVER_ROLE_ID]
    assert rule_role_labels(rule) == "幣號／代洗／AW"
    assert rule.required_roles == ()
    assert rule.required_game_roles == ()
    assert rule.min_quantity == rule.max_quantity == 1
    assert rule.vip_discount_allowed is False
    assert rule.point_benefits_allowed is False

    quote = calculate_price(rule, quantity=1)
    assert quote.base_amount == quote.total_amount == expected


def test_internal_aw_modal_quantity_and_exact_4t_per_round():
    # The existing three public AW price tiers must remain unchanged.
    assert len(AW_RULE_KEYS) == 3
    assert all(key.startswith("farm_aw_collision_") for key in AW_RULE_KEYS)

    draft = {}
    apply_self_service_category_selection(draft, INTERNAL_CATEGORY)
    detail = apply_self_service_item_group_selection(draft, "AW 子彈")
    assert detail is not None
    assert detail["quantity_input_mode"] == "modal"
    assert draft["order_rule_key"] == INTERNAL_AW_RULE
    assert _order_requires_credentials(draft) is True

    rule = ORDER_RULES[INTERNAL_AW_RULE]
    assert rule.category == INTERNAL_CATEGORY
    assert rule.allowed_roles == COIN_WASH_AW_RECEIVER_ROLES
    assert get_allowed_role_ids(rule) == [COIN_WASH_AW_RECEIVER_ROLE_ID]
    assert rule_role_labels(rule) == "幣號／代洗／AW"
    assert rule.required_roles == ()
    assert rule.required_game_roles == ()
    assert rule.vip_discount_allowed is False
    assert rule.point_benefits_allowed is False

    for rounds in (1, 250, 999999):
        assert validate_aw_quantity_for_rule(INTERNAL_AW_RULE, rounds)["rate_text"] == "4"
        assert aw_collision_original_amount(INTERNAL_AW_RULE, rounds) == rounds * 4
        quote = calculate_price(rule, quantity=rounds)
        assert quote.total_amount == rounds * 4

    with pytest.raises(ValueError):
        validate_aw_quantity_for_rule(INTERNAL_AW_RULE, 0)
    with pytest.raises(ValueError):
        validate_aw_quantity_for_rule(INTERNAL_AW_RULE, 1000000)


def test_internal_aw_keeps_special_direct_payment_calculation():
    rule = ORDER_RULES[INTERNAL_AW_RULE]
    quote = calculate_price(rule, quantity=37)
    result = self_service_financials.calculate_self_service_financials(
        rule,
        quote,
        {
            "manual_discount_percent": 50,
            "cash_coupon_amount": 250,
            "point_discount_coupon_amount": 100,
        },
    )
    assert result["customer_pay_amount"] == 148
    assert result["payout_base_amount"] == 148
    assert result["manual_discount_amount"] == 0
    assert result["cash_coupon_amount"] == 0
    assert result["point_discount_coupon_amount"] == 0


@pytest.mark.parametrize(
    "rule_key",
    [
        "staff_internal_ammo_dump_500m",
        "staff_internal_car_500m",
        "staff_internal_aw_collision",
    ],
)
def test_all_internal_services_use_existing_private_credential_flow(rule_key):
    assert _order_requires_credentials({
        "category": INTERNAL_CATEGORY,
        "order_rule_key": rule_key,
    })
    # Historic or recovered tickets can still be recognized from their stable rule.
    assert _order_requires_credentials({"order_rule_key": rule_key})
    assert not _order_requires_credentials({"category": "valorant", "order_rule_key": "valorant_entertain_ng"})


def test_internal_credential_modal_has_internal_title():
    modal = OrderCredentialModal(1234, internal_order=True)
    assert modal.title == "內部服務登入資料"
    legacy_modal = OrderCredentialModal(1234)
    assert legacy_modal.title == "代肝／代解登入資料"
