from __future__ import annotations

import pytest

from services import vip_monthly_order_discount as monthly_discount
from services import vip_monthly_benefits


def test_no_selected_monthly_voucher_has_no_discount():
    selected, amount = monthly_discount.resolve_vip_monthly_cash_discount(
        {"customer_id": "123"},
        has_point_benefit=False,
        max_discount_amount=600,
    )
    assert selected is None
    assert amount == 0


def _coupon(benefit_key: str, amount: int, benefit_id: int = 9) -> dict:
    return {
        "id": benefit_id,
        "benefit_key": benefit_key,
        "title": f"VIP 每月 {amount}T 折現券",
        "amount": amount,
    }


def test_selected_monthly_voucher_is_revalidated_and_clamped(monkeypatch):
    calls = []

    def fake_get(benefit_id, *, customer_id):
        calls.append((benefit_id, customer_id))
        return _coupon("monthly_coupon_200", 200)

    monkeypatch.setattr(vip_monthly_benefits, "get_available_cash_benefit", fake_get)
    selected, amount = monthly_discount.resolve_vip_monthly_cash_discount(
        {
            "customer_id": "123",
            "selected_vip_monthly_benefit_id": 9,
            "service_original_amount": 1500,
        },
        has_point_benefit=False,
        max_discount_amount=150,
    )
    assert calls == [(9, "123")]
    assert selected["id"] == 9
    assert amount == 150

    note = monthly_discount.build_vip_monthly_discount_note(
        selected,
        amount,
        formatter=lambda value: f"{value:,}T",
    )
    assert note == "VIP 每月 200T 折現券 -150T"
    assert monthly_discount.build_vip_monthly_discount_result(selected, amount) == {
        "vip_monthly_benefit_id": 9,
        "vip_monthly_benefit_key": "monthly_coupon_200",
        "vip_monthly_benefit_title": "VIP 每月 200T 折現券",
        "vip_monthly_cash_amount": 150,
    }


def test_200_coupon_requires_1500_original_service_amount(monkeypatch):
    monkeypatch.setattr(
        vip_monthly_benefits,
        "get_available_cash_benefit",
        lambda *args, **kwargs: _coupon("monthly_coupon_200", 200),
    )
    with pytest.raises(ValueError, match="1,500T"):
        monthly_discount.resolve_vip_monthly_cash_discount(
            {
                "customer_id": "123",
                "selected_vip_monthly_benefit_id": 9,
                "service_original_amount": 1499,
            },
            has_point_benefit=False,
            max_discount_amount=1499,
        )


def test_500_coupon_requires_4000_original_service_amount(monkeypatch):
    monkeypatch.setattr(
        vip_monthly_benefits,
        "get_available_cash_benefit",
        lambda *args, **kwargs: _coupon("monthly_coupon_500", 500),
    )
    with pytest.raises(ValueError, match="4,000T"):
        monthly_discount.resolve_vip_monthly_cash_discount(
            {
                "customer_id": "123",
                "selected_vip_monthly_benefit_id": 9,
                "service_original_amount": 3999,
            },
            has_point_benefit=False,
            max_discount_amount=3999,
        )


def test_threshold_uses_original_amount_before_vip_discount(monkeypatch):
    monkeypatch.setattr(
        vip_monthly_benefits,
        "get_available_cash_benefit",
        lambda *args, **kwargs: _coupon("monthly_coupon_200", 200),
    )
    selected, amount = monthly_discount.resolve_vip_monthly_cash_discount(
        {"customer_id": "123", "selected_vip_monthly_benefit_id": 9},
        has_point_benefit=False,
        max_discount_amount=1410,
        original_service_amount=1500,
    )
    assert selected["benefit_key"] == "monthly_coupon_200"
    assert amount == 200


def test_monthly_voucher_rejects_point_benefit_conflict():
    with pytest.raises(ValueError, match="只能擇一"):
        monthly_discount.resolve_vip_monthly_cash_discount(
            {"customer_id": "123", "selected_vip_monthly_benefit_id": 9},
            has_point_benefit=True,
            max_discount_amount=600,
        )


def test_monthly_voucher_requires_customer_identity():
    with pytest.raises(ValueError, match="會員身分"):
        monthly_discount.resolve_vip_monthly_cash_discount(
            {"selected_vip_monthly_benefit_id": 9},
            has_point_benefit=False,
            max_discount_amount=600,
        )


def test_monthly_voucher_rejects_unavailable_selection(monkeypatch):
    monkeypatch.setattr(vip_monthly_benefits, "get_available_cash_benefit", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="已使用、已保留或已失效"):
        monthly_discount.resolve_vip_monthly_cash_discount(
            {"customer_id": "123", "selected_vip_monthly_benefit_id": 9},
            has_point_benefit=False,
            max_discount_amount=600,
        )
