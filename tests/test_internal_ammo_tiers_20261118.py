"""2026-11-18 internal 100/200/300M ammo tiers: same named/unnamed amounts.

New offers are full-worker payout with zero CS/store margin, while the
existing 500M named/unnamed split remains exactly unchanged.
"""
from __future__ import annotations

import pytest

from services.order_rules import ORDER_RULES, calculate_price
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.quick_order_v2 import QUICK_ORDER_V2_CHANNELS, build_entry_embed
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
    is_full_worker_payout_rule,
)
from services.self_service_financials import calculate_self_service_financials
from services.staff_internal_ammo_dump_policy import (
    ADDITIONAL_AMMO_DUMP_PRICES, AMMO_DUMP_PRICES,
    NAMED_SELECTION_KEY, require_ammo_dump_named_selection,
)
from services.staff_internal_ammo_dump_ui import InternalAmmoNamedView


@pytest.mark.parametrize("millions,price", [(100,550),(200,1080),(300,1620)])
@pytest.mark.parametrize("named", [True,False])
def test_new_ammo_tier_named_unnamed_identical_and_full_worker(millions,price,named):
    key = f"staff_internal_ammo_dump_{millions}m"
    rule = ORDER_RULES[key]
    assert rule.category == "staff_internal"
    assert rule.price == price
    assert rule.vip_discount_allowed is False
    assert rule.point_benefits_allowed is False
    assert rule.loyalty_benefits_enabled is False
    assert is_full_worker_payout_rule(key)

    quote = calculate_price(rule,quantity=1)
    data = {
        NAMED_SELECTION_KEY: named,
        "manual_discount_percent": 50, "cash_coupon_amount": 700,
        "manual_staff_amount": 3, "point_discount_coupon_amount": 500,
    }
    details = calculate_self_service_financials(rule,quote,data)
    require_ammo_dump_named_selection(rule,data)
    for name in ("customer_pay_amount","payout_base_amount","service_original_amount"):
        assert details[name] == price, (key,name)
    assert details["store_margin_amount"] == 0
    assert details["customer_service_payout_amount"] == 0
    assert details["store_retained_amount"] == 0
    assert details["cash_coupon_amount"] == 0
    assert details["manual_discount_amount"] == 0

    payout = calculate_one_companion_one_guard_order_payout(
        rule_key=key,total_amount=details["payout_base_amount"],
        worker_roles=[("worker-1","booster")],
        customer_service_total_amount=details["customer_pay_amount"],
    )
    assert payout is not None
    assert payout.total_worker_payout == price
    assert payout.customer_service_payout == 0

    view=InternalAmmoNamedView(
        customer_id=1,channel_id=2,panel_message_id=3,rule_key=key
    )
    options=view.children[0].options
    assert [option.value for option in options] == ["named","unnamed"]
    assert all(f"{price:,}T" in option.label for option in options)


def test_internal_catalog_and_entry_panel_only_add_three_tiers():
    groups=SELF_SERVICE_ORDER_CATALOG["staff_internal"]
    assert [g["label"] for g in groups] == [
        "倒子彈｜100M","倒子彈｜200M","倒子彈｜300M",
        "倒子彈｜500M","撞車｜500M","AW 子彈",
    ]
    assert ADDITIONAL_AMMO_DUMP_PRICES == {100:550,200:1080,300:1620}
    panel=build_entry_embed(QUICK_ORDER_V2_CHANNELS["staff_internal"])
    for marker in ("100M","550T","200M","1,080T","300M","1,620T",
                   "有掛名 2,650T","無掛名 3,000T","4T／發"):
        assert marker in panel.description
    assert AMMO_DUMP_PRICES["staff_internal_ammo_dump_500m"] == (2650,3000,2650)


@pytest.mark.parametrize("named,customer,cs,store",[(True,2650,0,0),(False,3000,88,262)])
def test_existing_500m_named_and_unnamed_policy_untouched(named,customer,cs,store):
    rule=ORDER_RULES["staff_internal_ammo_dump_500m"]
    quote=calculate_price(rule)
    details=calculate_self_service_financials(rule,quote,{NAMED_SELECTION_KEY:named})
    assert details["customer_pay_amount"] == customer
    assert details["payout_base_amount"] == 2650
    assert details["customer_service_payout_amount"] == cs
    assert details["store_retained_amount"] == store


def test_missing_named_selection_is_not_silently_unnamed_for_new_tier():
    key="staff_internal_ammo_dump_100m"
    rule=ORDER_RULES[key]
    with pytest.raises(ValueError,match="先由客服選擇"):
        require_ammo_dump_named_selection(rule,{})
    quote=calculate_price(rule)
    assert calculate_self_service_financials(rule,quote,{})["manual_price_missing"]
