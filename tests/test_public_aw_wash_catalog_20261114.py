"""The public MOWAN catalogue must match the current Discord AW/wash products.

The retired halfcoin variants are still readable for old order history but
must never be offered or accepted for a new public order.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.order_rules import (
    AW_COLLISION_RECEIVER_ROLE_ID,
    HALFCOIN_RECEIVER_ROLE_ID,
    ORDER_RULES,
    get_allowed_role_ids,
)
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.order_catalog_cards import (
    clear_order_catalog_cards_cache,
    get_grouped_order_catalog_cards,
    get_order_group_detail,
)
from web.app.services.public_checkout import build_public_quote

ROOT = Path(__file__).resolve().parents[1]

RETIRED = {"farm_halfcoin_120m", "farm_halfcoin_360m"}
WASH = {"farm_coin_wash_car", "farm_coin_wash_ammo_dump"}
AW_TIERS = (
    ("farm_aw_collision_1_100", 1, 100, 10, 100),
    ("farm_aw_collision_101_500", 101, 500, 9, 455),
    ("farm_aw_collision_501_plus", 501, 999999, 8, 2004),
)


def _by_key(groups):
    return {str(group["key"]): group for group in groups}


def test_public_site_has_current_wash_and_aw_but_no_retired_halfcoin():
    clear_order_catalog_cards_cache()
    full = _by_key(get_grouped_order_catalog("farm"))
    cards = _by_key(get_grouped_order_catalog_cards("farm"))
    assert "halfcoin" not in full
    assert "halfcoin" not in cards
    assert "coin_wash" in full and "coin_wash" in cards
    assert "aw_collision" in full and "aw_collision" in cards
    assert "哈夫幣代洗" not in [item["label"] for item in full.values()]
    assert all(
        variant["rule_key"] not in RETIRED
        for group in full.values()
        for variant in group["variants"]
    )
    assert get_order_group_detail("halfcoin") is None

    wash = full["coin_wash"]
    assert {v["rule_key"] for v in wash["variants"]} == WASH
    assert wash["starting_price_text"] == "客服報價"
    assert cards["coin_wash"]["variant_count"] == 2
    assert all(v["pricing_type"] == "manual" for v in wash["variants"])

    aw = full["aw_collision"]
    assert aw["label"] == "AW 代撞"
    assert cards["aw_collision"]["variant_count"] == 3
    assert cards["aw_collision"]["starting_price_text"] == "4T／發起"
    assert "4.5T" in aw["description"]


@pytest.mark.parametrize("rule_key", sorted(RETIRED))
def test_forged_retired_public_order_quote_is_rejected(rule_key):
    with pytest.raises(ValueError, match="已停止提供新訂單"):
        build_public_quote(rule_key=rule_key, quantity=1)


@pytest.mark.parametrize("rule_key", sorted(WASH))
def test_new_wash_product_uses_original_receiver_and_manual_cs_price(rule_key):
    assert get_allowed_role_ids(ORDER_RULES[rule_key]) == [HALFCOIN_RECEIVER_ROLE_ID]
    result = build_public_quote(rule_key=rule_key, quantity=1)
    assert result["manual_quote"] is True
    assert result["item"].startswith("對外洗幣")


@pytest.mark.parametrize("rule_key,minimum,maximum,rate_x2,first_quote", AW_TIERS)
def test_aw_public_variant_bounds_and_half_t_compatible_quote(
    rule_key, minimum, maximum, rate_x2, first_quote
):
    group = get_order_group_detail("aw_collision")
    variant = next(v for v in group["variants"] if v["rule_key"] == rule_key)
    assert variant["quantity_enabled"] is True
    assert variant["min_quantity"] == minimum
    assert variant["max_quantity"] == maximum
    assert variant["aw_rate_x2"] == rate_x2
    assert variant["unit_label"] == "發"
    assert get_allowed_role_ids(ORDER_RULES[rule_key]) == [AW_COLLISION_RECEIVER_ROLE_ID]

    quote = build_public_quote(rule_key=rule_key, quantity=minimum)
    expected = (minimum * rate_x2 + 1) // 2
    assert quote["original_amount"] == expected
    assert quote["customer_pay_amount"] == expected
    assert quote["manual_quote"] is False
    assert quote["quantity"] == minimum
    if minimum == 101:
        assert quote["original_amount"] == 455
        assert "4.5T" in variant["price_text"]
    if minimum == 501:
        assert quote["original_amount"] == 2004

    for invalid in (minimum - 1, maximum + 1):
        if invalid > 0:
            with pytest.raises(ValueError):
                build_public_quote(rule_key=rule_key, quantity=invalid)


@pytest.mark.parametrize("quantity,expected", [(101, 455), (102, 459), (499, 2246), (500, 2250)])
def test_half_t_aw_tier_rounds_final_amount_up(quantity, expected):
    quote = build_public_quote(rule_key="farm_aw_collision_101_500", quantity=quantity)
    assert quote["base_amount"] == expected


def test_aw_frontend_uses_same_half_t_integer_formula_and_direct_input():
    script = (ROOT / "web/app/static/js/mw_order.js").read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/order_catalog.html").read_text(encoding="utf-8")
    assert "quantity * Number(activeVariant.aw_rate_x2) / 2" in script
    assert "Math.ceil(" in script
    assert "mw-aw-quantity-input" in script
    assert 'id="mw-aw-quantity-input"' in template
