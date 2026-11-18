"""100M/200M/300M internal ammo plans, with naming parity and 500M compatibility."""
from __future__ import annotations

import pytest

from services.coin_wash_urgent_policy import urgent_fee_for_rule
from services.one_companion_one_guard_payout import is_full_worker_payout_rule
from services.order_rules import (
    FULL_SOURCE_AUTHORITY_RULE_KEYS,
    HALFCOIN_RECEIVER_ROLES,
    calculate_price,
    get_base_rule,
)
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_PRICES_BY_RULE,
    NAMED_SELECTION_KEY,
    calculate_internal_ammo_dump_financials,
    require_ammo_dump_named_selection,
)


@pytest.mark.parametrize("millions, price", [(100, 550), (200, 1080), (300, 1620)])
def test_new_internal_ammo_tiers_are_same_price_with_or_without_name(millions, price):
    rule_key = f"staff_internal_ammo_dump_{millions}m"
    rule = get_base_rule(rule_key)
    assert rule.category == "staff_internal"
    assert rule.price == price
    assert rule.allowed_roles == HALFCOIN_RECEIVER_ROLES
    assert rule_key in FULL_SOURCE_AUTHORITY_RULE_KEYS
    assert is_full_worker_payout_rule(rule_key)
    assert urgent_fee_for_rule(rule_key) == 260
    assert AMMO_DUMP_PRICES_BY_RULE[rule_key] == (price, price, price)
    quote = calculate_price(rule, quantity=1)

    with pytest.raises(ValueError, match="先由客服選擇"):
        require_ammo_dump_named_selection(rule, {})

    for named in (True, False):
        data = {NAMED_SELECTION_KEY: named}
        require_ammo_dump_named_selection(rule, data)
        financials = calculate_internal_ammo_dump_financials(quote, data, rule)
        assert financials["customer_pay_amount"] == price
        assert financials["payout_base_amount"] == price
        assert financials["store_margin_amount"] == 0
        assert financials["customer_service_payout_amount"] == 0
        assert financials["store_retained_amount"] == 0


def test_internal_ammo_500m_named_margin_and_cs_share_unchanged():
    rule_key = "staff_internal_ammo_dump_500m"
    rule = get_base_rule(rule_key)
    quote = calculate_price(rule, quantity=1)
    for named, customer, worker, cs, retained in (
        (True, 2650, 2650, 0, 0),
        (False, 3000, 2650, 88, 262),
    ):
        financials = calculate_internal_ammo_dump_financials(
            quote, {NAMED_SELECTION_KEY: named}, rule
        )
        assert financials["customer_pay_amount"] == customer
        assert financials["payout_base_amount"] == worker
        assert financials["customer_service_payout_amount"] == cs
        assert financials["store_retained_amount"] == retained


def test_internal_discord_catalog_includes_three_new_tiers_without_hiding_500m():
    groups = {entry["label"]: entry for entry in SELF_SERVICE_ORDER_CATALOG["staff_internal"]}
    assert "倒子彈｜500M" in groups
    assert "倒子彈｜100M～300M" in groups
    assert [entry["rule_key"] for entry in groups["倒子彈｜100M～300M"]["details"]] == [
        "staff_internal_ammo_dump_100m",
        "staff_internal_ammo_dump_200m",
        "staff_internal_ammo_dump_300m",
    ]
