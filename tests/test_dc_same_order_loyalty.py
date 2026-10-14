from __future__ import annotations

from types import SimpleNamespace

import discord

from services import loyalty_benefits as loyalty
from services import self_service_financials as financials
from services import self_service_selection_runtime as selection


def _same_order_coupon(units: float = 1.0) -> dict:
    return {
        "id": None,
        "source": "same_order",
        "same_order": True,
        "earned_count": 1,
        "scope_key": "delta|basic_entertain",
        "rule_key": "basic_entertain_single",
        "rule_label": "三角洲娛樂陪〈端遊〉",
        "pricing_type": "hourly",
        "player_count": 1,
        "benefit_kind": "extra_hours",
        "benefit_units": units,
        "threshold_units": 10.0,
        "title": f"三角洲娛樂陪〈端遊〉｜折抵 {units:g} 小時額度",
    }


def test_dc_benefit_selector_shows_same_order_reward(monkeypatch):
    data = {"customer_id": 123, "quantity": 10, "player_count": 1}
    selection.SELF_SERVICE_ORDER_SELECTIONS = {999: data}
    selection.POINT_REDEEM_ITEMS = []
    monkeypatch.setattr(selection, "_to_int", lambda value, default=0: default if value in (None, "") else int(value))
    monkeypatch.setattr(selection, "get_customer_point_balance_for_order", lambda _customer_id: 0)
    monkeypatch.setattr(selection, "remember_order_data", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(selection, "get_selected_order_point_benefit", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(loyalty, "list_applicable_coupons", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(loyalty, "preview_same_order_benefit", lambda *_args, **_kwargs: _same_order_coupon())

    from services import vip_monthly_benefits
    monkeypatch.setattr(vip_monthly_benefits, "list_available_cash_benefits", lambda _customer_id: [])

    rule = SimpleNamespace(key="basic_entertain_single")
    view = selection.SelfServicePointBenefitView(
        customer_id=123,
        channel_id=999,
        panel_message_id=None,
        rule=rule,
    )

    select = next(item for item in view.children if isinstance(item, discord.ui.Select))
    same_order = next(option for option in select.options if option.value == "same_order")
    assert "本單累積福利" in same_order.label
    assert "折抵 1 小時" in same_order.label


def test_dc_same_order_reward_reduces_customer_pay_without_cutting_payout(monkeypatch):
    rule = SimpleNamespace(
        key="basic_entertain_single",
        category="basic",
        pricing_type="hourly",
        unit_label="H",
        point_benefits_allowed=True,
    )
    price_result = SimpleNamespace(
        base_amount=3200,
        specify_fee=0,
        staff_adjustment_amount=0,
        service_quantity=10,
    )
    data = {
        "customer_id": 123,
        "quantity": 10,
        "player_count": 1,
        "selected_same_order_benefit": True,
    }

    financials.POINT_REDEEM_ITEMS_BY_KEY = {}
    financials.ORDER_POINT_BENEFIT_SPECS = {}
    monkeypatch.setattr(financials, "_to_int", lambda value, default=0: default if value in (None, "") else int(value), raising=False)
    monkeypatch.setattr(
        financials,
        "_resolve_self_service_discount_rate",
        lambda *_args, **_kwargs: (98.0, "白金魔丸 自動 VIP 折扣", "vip", "白金魔丸"),
    )
    monkeypatch.setattr(financials, "resolve_vip_monthly_cash_discount", lambda *_args, **_kwargs: (None, 0))

    from services import order_discounts
    monkeypatch.setattr(
        financials,
        "allocate_store_absorbed_fixed_discount",
        order_discounts.allocate_store_absorbed_fixed_discount,
        raising=False,
    )
    monkeypatch.setattr(loyalty, "preview_same_order_benefit", lambda *_args, **_kwargs: _same_order_coupon())
    monkeypatch.setattr(loyalty, "calculate_coupon_service_value", lambda **_kwargs: 320)
    monkeypatch.setattr(
        loyalty,
        "coupon_service_note",
        lambda coupon: "本單累積福利：折抵 1 小時服務額度" if coupon else "",
    )

    result = financials.calculate_self_service_financials(rule, price_result, data)

    assert result["customer_pay_amount"] == 2816
    assert result["payout_base_amount"] == 3136
    assert result["store_absorbed_amount"] == 320
    assert result["benefit_discount_amount"] == 320
    assert result["benefit_coupon_id"] is None
    assert result["benefit_coupon"]["source"] == "same_order"


def test_dc_same_order_snapshot_is_recognized_as_consumed_reward():
    import json

    coupon = _same_order_coupon()
    row = {
        "amount": 0,
        "customer_pay_amount": 0,
        "price_snapshot_json": json.dumps(
            {
                "service_original_amount": 320,
                "discount_rate_percent": 98,
                "payout_base_amount": 314,
                "customer_pay_amount": 0,
                "benefit_coupon": coupon,
            },
            ensure_ascii=False,
        ),
    }

    assert loyalty._extract_same_order_benefit_count(row) == 1
    assert loyalty._qualifying_paid_amount(row) == 314
