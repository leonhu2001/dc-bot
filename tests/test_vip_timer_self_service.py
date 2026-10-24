from __future__ import annotations

import pytest

import services.vip_timer_self_service as bridge
from services.order_rules import ORDER_RULES
from services.vip_timer_catalog_guard import is_public_timer_rule


def test_timer_self_service_catalog_only_contains_current_hourly_products():
    groups = bridge.build_vip_timer_self_service_catalog()

    assert groups
    assert all(1 <= len(group.get("details") or []) <= 25 for group in groups)

    seen_values: set[str] = set()
    for group in groups:
        for detail in group.get("details") or []:
            rule_key = str(detail.get("rule_key") or "")
            rule = ORDER_RULES.get(rule_key)

            assert rule is not None
            assert str(getattr(rule, "pricing_type", "")) == "hourly"
            assert is_public_timer_rule(rule_key)
            assert detail.get("quantity_unit") == "計時"
            assert int(detail.get("min_quantity") or 0) == 1
            assert int(detail.get("max_quantity") or 0) == 1
            assert str(detail.get("value") or "") not in seen_values
            seen_values.add(str(detail.get("value") or ""))


def test_prepare_timer_draft_disables_normal_checkout_benefits():
    data = {
        "category": "apex",
        "quantity": 4,
        "specified_staff_ids": ["123"],
        "selected_point_benefit_key": "discount_20",
        "selected_benefit_coupon_id": 99,
        "manual_discount_percent": 90,
        "cash_coupon_amount": 200,
        "payment_method": "轉帳",
    }

    bridge.prepare_vip_timer_draft(data)

    assert data["category"] == bridge.VIP_TIMER_CATEGORY
    assert data["vip_timer_order"] is True
    assert data["quantity"] == 1
    assert data["companion_preference"] == "不指定陪玩/打手"
    assert "specified_staff_ids" not in data
    assert "selected_point_benefit_key" not in data
    assert "selected_benefit_coupon_id" not in data
    assert "manual_discount_percent" not in data
    assert "cash_coupon_amount" not in data
    assert "payment_method" not in data


def test_zero_timer_financials_keeps_shape_but_removes_upfront_money():
    raw = {
        "customer_pay_amount": 800,
        "payout_base_amount": 800,
        "original_amount": 800,
        "manual_discount_amount": 20,
        "cash_coupon_amount": 100,
        "benefit_coupon_id": 7,
        "point_benefit_key": "discount_20",
        "service_bonus_text": "5送1",
        "price_formula_version": 2,
        "manual_price_missing": True,
    }

    result = bridge.zero_vip_timer_financials(raw)

    assert result["customer_pay_amount"] == 0
    assert result["payout_base_amount"] == 0
    assert result["original_amount"] == 0
    assert result["manual_discount_amount"] == 0
    assert result["cash_coupon_amount"] == 0
    assert result["benefit_coupon_id"] is None
    assert result["point_benefit_key"] is None
    assert result["service_bonus_text"] is None
    assert result["price_formula_version"] == 2
    assert result["manual_price_missing"] is False
    assert result["vip_timer"] is True


def test_timer_eligibility_requires_platinum_and_no_open_order(monkeypatch):
    monkeypatch.setattr(bridge, "_customer_vip_name", lambda customer_id: "白金魔丸")
    monkeypatch.setattr(bridge, "has_open_vip_timer", lambda customer_id: False)
    bridge.assert_vip_timer_self_service_eligible(123)

    monkeypatch.setattr(bridge, "_customer_vip_name", lambda customer_id: "金級魔丸")
    with pytest.raises(ValueError, match="白金級會員以上"):
        bridge.assert_vip_timer_self_service_eligible(123)

    monkeypatch.setattr(bridge, "_customer_vip_name", lambda customer_id: "白金魔丸")
    monkeypatch.setattr(bridge, "has_open_vip_timer", lambda customer_id: True)
    with pytest.raises(ValueError, match="已有一張"):
        bridge.assert_vip_timer_self_service_eligible(123)
