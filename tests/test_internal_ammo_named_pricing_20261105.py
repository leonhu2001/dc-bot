from __future__ import annotations

import discord
import pytest

from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
    is_full_worker_payout_rule,
)
from services.order_rules import ORDER_RULES, calculate_price
from services.quick_order_v2 import QUICK_ORDER_V2_CHANNELS, build_entry_embed
from services.self_service_financials import (
    add_self_service_financial_breakdown_fields,
    calculate_self_service_financials,
)
from services.self_service_selection_state import (
    apply_self_service_item_group_selection,
)
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RULE_KEY,
    NAMED_SELECTION_KEY,
    require_ammo_dump_named_selection,
    selected_ammo_dump_named,
)
from services.staff_internal_ammo_dump_ui import (
    InternalAmmoNamedButton,
    InternalAmmoNamedView,
)


@pytest.mark.parametrize(
    ("named", "customer_price", "store_margin"),
    [(True, 2650, 0), (False, 3000, 350)],
)
def test_ammo_named_selection_is_only_price_input_and_worker_gets_full_2650(
    named, customer_price, store_margin,
):
    rule = ORDER_RULES[AMMO_DUMP_RULE_KEY]
    quote = calculate_price(rule, quantity=1)
    data = {
        NAMED_SELECTION_KEY: named,
        "manual_staff_amount": 1,
        "manual_discount_percent": 20,
        "cash_coupon_amount": 900,
        "point_discount_coupon_amount": 600,
        "selected_point_benefit_key": "discount_20",
    }

    result = calculate_self_service_financials(rule, quote, data)
    assert result["manual_price_missing"] is False
    assert result["customer_pay_amount"] == customer_price
    assert result["service_original_amount"] == customer_price
    assert result["payout_base_amount"] == 2650
    assert result["store_margin_amount"] == store_margin
    assert result["manual_staff_amount"] is None
    assert result["manual_discount_amount"] == 0
    assert result["cash_coupon_amount"] == 0
    assert result["point_discount_coupon_amount"] == 0
    assert result["store_absorbed_amount"] == 0

    payout = calculate_one_companion_one_guard_order_payout(
        rule_key=AMMO_DUMP_RULE_KEY,
        total_amount=result["payout_base_amount"],
        worker_roles=[("worker-1", "booster")],
        named_bonus_worker_ids=["worker-1"],
        customer_service_total_amount=result["customer_pay_amount"],
    )
    assert payout is not None
    assert payout.total_worker_payout == 2650
    assert payout.worker_payouts[0].final_payout == 2650
    assert payout.worker_payouts[0].named_bonus_amount == 0
    assert payout.customer_service_payout == 0

    embed = discord.Embed()
    add_self_service_financial_breakdown_fields(embed, result)
    fields = {f.name: f.value for f in embed.fields}
    assert fields["顧客應付"] == f"{customer_price:,}"
    assert fields["打手分潤基準"] == "2,650"
    assert fields["掛名狀態"] == ("有掛名" if named else "無掛名")
    if not named:
        assert "350T" in fields["店家收入差額"]
    else:
        assert "店家收入差額" not in fields


def test_ammo_requires_explicit_customer_service_choice_before_dispatch():
    rule = ORDER_RULES[AMMO_DUMP_RULE_KEY]
    quote = calculate_price(rule, quantity=1)
    data = {}
    assert selected_ammo_dump_named(data) is None
    with pytest.raises(ValueError, match="先由客服選擇"):
        require_ammo_dump_named_selection(rule, data)
    assert calculate_self_service_financials(rule, quote, data)["manual_price_missing"] is True

    for invalid in ("false", "true", 0, 1, ""):
        data[NAMED_SELECTION_KEY] = invalid
        with pytest.raises(ValueError, match="先由客服選擇"):
            require_ammo_dump_named_selection(rule, data)

    data[NAMED_SELECTION_KEY] = False
    require_ammo_dump_named_selection(rule, data)
    data[NAMED_SELECTION_KEY] = True
    require_ammo_dump_named_selection(rule, data)


def test_named_state_clears_when_switching_product():
    data = {
        "category": "staff_internal",
        "item_group": "倒子彈｜500M",
        "order_rule_key": AMMO_DUMP_RULE_KEY,
        NAMED_SELECTION_KEY: False,
        "staff_internal_ammo_named_set_by": 123,
        "staff_internal_ammo_named_set_at": "now",
        "store_margin_amount": 350,
    }
    apply_self_service_item_group_selection(data, "撞車｜500M")
    assert data["order_rule_key"] == "staff_internal_car_500m"
    assert NAMED_SELECTION_KEY not in data
    assert "staff_internal_ammo_named_set_by" not in data
    assert "store_margin_amount" not in data


def test_ticket_staff_checkbox_has_distinct_named_and_unnamed_options():
    for named, label in [
        (None, "待選擇"),
        (True, "有掛名"),
        (False, "無掛名"),
    ]:
        data = {} if named is None else {NAMED_SELECTION_KEY: named}
        button = InternalAmmoNamedButton(customer_id=1, channel_id=99, data=data)
        assert label in button.label
        assert button.custom_id == "staff_internal_ammo_named_button"
        assert button.row == 4

    view = InternalAmmoNamedView(customer_id=1, channel_id=99, panel_message_id=123)
    assert len(view.children) == 1
    control = view.children[0]
    assert [o.value for o in control.options] == ["named", "unnamed"]


def test_store_internal_panel_displays_both_ammo_prices_and_cs_choice():
    panel = build_entry_embed(QUICK_ORDER_V2_CHANNELS["staff_internal"])
    assert "有掛名 2,650T" in panel.description
    assert "無掛名 3,000T" in panel.description
    assert "由客服勾選" in panel.description


@pytest.mark.parametrize(
    "rule_key",
    [
        "staff_internal_ammo_dump_500m",
        "staff_internal_car_500m",
        "staff_internal_aw_collision",
        "farm_halfcoin_120m",
        "farm_aw_collision_501_plus",
    ],
)
def test_special_internal_order_payout_matches_external_full_worker_policy(rule_key):
    assert is_full_worker_payout_rule(rule_key) is True
