from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vip_monthly_discount_stays_out_of_legacy_financial_runtime():
    financial = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    domain = (ROOT / "services" / "vip_monthly_order_discount.py").read_text(encoding="utf-8")

    assert "resolve_vip_monthly_cash_discount" in financial
    assert "get_available_cash_benefit" not in financial
    assert "get_available_cash_benefit" in domain
    assert (ROOT / "services" / "self_service_financials.py").stat().st_size <= 42000
