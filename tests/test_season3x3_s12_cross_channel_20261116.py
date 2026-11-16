"""S12 3×3 owner-approved price card is one Bot/Web rule of truth.

Early booking is NOT a customer-selectable option. Only a CS-entered shared
fixed cash discount of 500T is permitted after checking eligibility.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.order_discounts import allocate_store_absorbed_fixed_discount
from services.order_rules import (ORDER_RULES, calculate_price, get_base_rule,
    SEASON_3X3_EARLY_BOOKING_DISCOUNT_AMOUNT, SEASON_3X3_EARLY_BOOKING_DISCOUNT_SOURCE)
from services.orders import get_order_item_details_for_group
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.public_checkout import build_public_quote


ROOT = Path(__file__).resolve().parents[1]

S12_BOX_PRICES = {
    "farm_season_3x3_normal": ([], 5500),
    "farm_season_3x3_dc_skin": (["skin"], 8000),
    "farm_season_3x3_dc_loss": (["loss_cover"], 6000),
    "farm_season_3x3_dc_skin_loss": (["skin", "loss_cover"], 8500),
}


@pytest.mark.parametrize("rule_key,options_and_price", S12_BOX_PRICES.items())
def test_3x3_dc_priced_variants_equal_web_adjustment_quote(rule_key, options_and_price):
    adjustments, approved = options_and_price
    assert get_base_rule(rule_key).price == approved
    assert ORDER_RULES[rule_key].price == approved
    dc_total = calculate_price(ORDER_RULES[rule_key], quantity=1).total_amount
    web = build_public_quote(
        rule_key="farm_season_3x3_normal",
        quantity=1,
        customer_adjustments=adjustments,
    )
    assert dc_total == approved
    assert web["base_amount"] + web["adjustment_amount"] == approved
    assert web["customer_pay_amount"] == approved


def test_contract_quantity_and_limit_are_from_same_rule():
    contract = ORDER_RULES["farm_season_3x3_contract"]
    assert contract.price == 600
    assert contract.max_quantity == 7
    for qty in (1, 2, 7):
        dc_total = calculate_price(contract, quantity=qty).total_amount
        web = build_public_quote(rule_key=contract.key, quantity=qty)
        assert dc_total == web["customer_pay_amount"] == qty * 600
    with pytest.raises(ValueError, match="最多只能選 7 個"):
        build_public_quote(rule_key=contract.key, quantity=8)


def test_public_card_shows_new_image_and_owner_terms_but_no_booking_choice():
    group = next(g for g in get_grouped_order_catalog("farm") if g["key"] == "season_3x3")
    assert group["image_url"] == "/static/order_panels/delta_farm_3x3.png"
    assert "5,500T" in group["description"]
    assert "8,000T" in group["description"]
    assert "外觀" in group["description"]
    assert "客服" in group["description"]
    variant = next(v for v in group["variants"] if v["rule_key"] == "farm_season_3x3_normal")
    assert variant["price"] == 5500
    assert variant["label"] == "3×3安全箱"
    extras = {item["key"]: item for item in variant["customer_adjustments"]}
    assert set(extras) == {"skin", "loss_cover"}
    assert extras["skin"] == {"key": "skin", "label": "外觀", "amount": 2500}
    assert extras["loss_cover"]["amount"] == 500
    assert "early_booking" not in extras


def test_early_booking_is_manual_shared_discount_not_web_selection():
    with pytest.raises(ValueError, match="客服"):
        build_public_quote(
            rule_key="farm_season_3x3_normal",
            customer_adjustments=["early_booking"],
        )
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=5500,
        fixed_discount_amount=500,
    )
    assert result.customer_pay_amount == 5000
    assert result.payout_base_amount == 5000
    assert result.store_absorbed_amount == 0

    with_exterior = allocate_store_absorbed_fixed_discount(
        after_percent_amount=8000, fixed_discount_amount=500,
    )
    assert with_exterior.customer_pay_amount == 7500
    assert with_exterior.payout_base_amount == 7500
    assert with_exterior.store_absorbed_amount == 0

    source = (ROOT / "services/self_service_ui_runtime.py").read_text(encoding="utf-8")
    assert 'data["fixed_discount_amount"] = coupon_amount' in source
    assert 'data["cash_coupon_amount"] = coupon_amount' in source
    assert "共同分攤，折後金額計入分潤基準" in source
