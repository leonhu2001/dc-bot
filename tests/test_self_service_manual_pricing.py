from pathlib import Path
from types import SimpleNamespace

import pytest

from services import self_service_manual_pricing as pricing


ROOT = Path(__file__).resolve().parents[1]


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _allocate(*, after_percent_amount, fixed_discount_amount):
    return SimpleNamespace(
        payout_base_amount=after_percent_amount,
        store_absorbed_amount=fixed_discount_amount,
        customer_pay_amount=max(after_percent_amount - fixed_discount_amount, 0),
    )


def test_manual_pricing_parsers_preserve_existing_rules():
    assert pricing.parse_discount_percent_text("90%") == 90.0
    assert pricing.parse_discount_percent_text("") == 100.0
    assert pricing.parse_cash_amount_text("1,250") == 1250
    with pytest.raises(ValueError):
        pricing.parse_discount_percent_text("101")
    with pytest.raises(ValueError):
        pricing.parse_cash_amount_text("-1")


def test_manual_pricing_calculation_preserves_store_funded_fixed_discount():
    result = pricing.calculate_manual_price_adjustment(
        1000,
        {
            "manual_discount_mode": "pay_rate",
            "manual_discount_percent": 90,
            "fixed_discount_amount": 100,
            "manual_discount_reason": "VIP",
            "cash_coupon_reason": "客服折扣",
        },
        to_int=_to_int,
        allocate_store_absorbed_fixed_discount=_allocate,
    )

    assert result["customer_pay_amount"] == 800
    assert result["payout_base_amount"] == 900
    assert result["manual_discount_amount"] == 100
    assert result["store_absorbed_amount"] == 100


def test_legacy_discount_off_value_still_converts_to_pay_rate():
    assert pricing.resolve_manual_discount_rate_percent(
        {"manual_discount_percent": 10}
    ) == 90.0


def test_financial_runtime_delegates_manual_pricing_without_duplicating_implementation():
    source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    assert "manual_pricing.calculate_manual_price_adjustment(" in source
    assert "def _parse_discount_percent_text" not in source
    assert "def _parse_cash_amount_text" not in source
    assert len(source.encode("utf-8")) < 40_000
