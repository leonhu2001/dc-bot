"""Owner-approved S12 3×3 pricing, naming and staff-only reservation discount.

The public Website must quote the same effective OrderRule as Discord. A
reservation discount is a staff-entered, shared *fixed* discount—not a
customer-selectable adjustment or store-funded coupon.
"""
from __future__ import annotations

import pytest

from services.order_discounts import (
    FUNDING_SHARED,
    allocate_store_absorbed_fixed_discount,
    get_discount_funding_policy,
)
from services.order_rules import (
    ORDER_RULES,
    SEASON_3X3_EARLY_BOOKING_DISCOUNT_AMOUNT,
    SEASON_3X3_EARLY_BOOKING_DISCOUNT_SOURCE,
)
from services.quick_order_v2_price_lists import DELTA_FARM_PRICE_LISTS
from web.app.services.public_checkout import build_public_quote, _get_public_rule
from web.app.services.order_groups import get_grouped_order_catalog


def test_3x3_website_uses_exact_same_effective_rules_as_discord():
    for rule_key in (
        "farm_season_3x3_normal",
        "farm_season_3x3_contract",
    ):
        assert _get_public_rule(rule_key) == ORDER_RULES[rule_key]
    assert _get_public_rule("farm_season_3x3_normal").price == 5500
    assert _get_public_rule("farm_season_3x3_contract").price == 600


@pytest.mark.parametrize(
    ("selected_adjustments", "expected_total"),
    (
        ([], 5500),
        (["skin"], 8000),
        (["loss_cover"], 6000),
        (["skin", "loss_cover"], 8500),
    ),
)
def test_3x3_dc_and_web_total_parity(selected_adjustments, expected_total):
    quote = build_public_quote(
        rule_key="farm_season_3x3_normal",
        quantity=1,
        customer_adjustments=selected_adjustments,
    )
    rule = ORDER_RULES["farm_season_3x3_normal"]
    assert quote["base_amount"] == int(rule.price)
    assert quote["original_amount"] == expected_total
    assert quote["customer_pay_amount"] == expected_total
    assert "造型" not in str(quote["customer_adjustments"])
    if "skin" in selected_adjustments:
        assert any(
            part["key"] == "skin" and part["label"] == "外觀"
            for part in quote["customer_adjustments"]
        )


@pytest.mark.parametrize("quantity", (1, 2, 7))
def test_fate_contract_quote_uses_shared_unit_price(quantity):
    quote = build_public_quote(
        rule_key="farm_season_3x3_contract", quantity=quantity,
    )
    assert quote["original_amount"] == 600 * quantity
    assert quote["customer_pay_amount"] == 600 * quantity


def test_fate_contract_rejects_quantity_over_canonical_limit():
    with pytest.raises(ValueError, match="最多只能選 7 個"):
        build_public_quote(rule_key="farm_season_3x3_contract", quantity=8)


def test_reservation_is_only_a_manual_shared_cash_discount_not_customer_option():
    assert SEASON_3X3_EARLY_BOOKING_DISCOUNT_AMOUNT == 500
    assert get_discount_funding_policy(
        SEASON_3X3_EARLY_BOOKING_DISCOUNT_SOURCE
    ) == FUNDING_SHARED

    with pytest.raises(ValueError, match="只能由客服套用"):
        build_public_quote(
            rule_key="farm_season_3x3_normal",
            customer_adjustments=["early_booking"],
        )

    for price in (5500, 8000):
        result = allocate_store_absorbed_fixed_discount(
            after_percent_amount=price,
            fixed_discount_amount=SEASON_3X3_EARLY_BOOKING_DISCOUNT_AMOUNT,
        )
        assert result.customer_pay_amount == price - 500
        assert result.payout_base_amount == price - 500
        assert result.store_absorbed_amount == 0


def test_price_list_uses_wai_guan_and_explicit_staff_only_reservation_copy():
    text = DELTA_FARM_PRICE_LISTS["safe_box_3x3"]["text"]
    assert "安全箱 5500T" in text
    assert "安全箱＋外觀 8000T" in text
    assert "包損＋500T" in text
    assert "命運契約 600T／個" in text
    assert "賽前提前預約 −500T" in text
    assert "客服手動" in text
    assert "共同分擔" in text
    assert "造型" not in text
    assert "\\n" not in text  # actual linebreaks, not literal escaped slashes


def test_website_catalog_does_not_advertise_early_booking_as_adjustment():
    groups = get_grouped_order_catalog("farm")
    season = next(group for group in groups if group["key"] == "season_3x3")
    assert season
    for variant in season["variants"]:
        assert all(
            str(item.get("key") or "") != "early_booking"
            for item in variant.get("customer_adjustments", [])
        )
