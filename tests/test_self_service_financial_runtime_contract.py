from pathlib import Path
from types import SimpleNamespace

from services import self_service_financials as financials


ROOT = Path(__file__).resolve().parents[1]


def test_staff_price_helpers_are_real_financial_domain_functions_before_runtime_config():
    assert financials.get_self_service_staff_price({}) is None
    assert financials.get_self_service_staff_price({"manual_staff_amount": "450"}) == 450
    assert financials.get_self_service_staff_price({"manual_staff_amount": "1,250"}) == 1250
    assert financials.get_self_service_staff_price({"manual_staff_amount": -20}) == 0
    assert financials.get_self_service_staff_price({"manual_staff_amount": "bad"}) is None

    assert financials.is_self_service_staff_price_required(
        SimpleNamespace(key="custom_custom_order", pricing_type="fixed")
    )
    assert financials.is_self_service_staff_price_required(
        SimpleNamespace(key="normal", pricing_type="manual")
    )
    assert not financials.is_self_service_staff_price_required(
        SimpleNamespace(key="normal", pricing_type="fixed")
    )


def test_self_service_runtime_reexports_canonical_staff_price_helpers():
    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")
    financial_source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")

    assert "def get_self_service_staff_price" in financial_source
    assert "def is_self_service_staff_price_required" in financial_source
    assert "def get_self_service_staff_price" not in runtime_source
    assert "def is_self_service_staff_price_required" not in runtime_source
    assert "get_self_service_staff_price," in runtime_source
    assert "is_self_service_staff_price_required," in runtime_source


def test_financial_runtime_missing_dependencies_fail_fast():
    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")

    assert "present_financial_keys = financial_keys.intersection(namespace)" in runtime_source
    assert "missing_financial_keys = sorted(financial_keys.difference(namespace))" in runtime_source
    assert "if present_financial_keys and missing_financial_keys:" in runtime_source
    assert "self-service financial runtime missing dependencies" in runtime_source
    assert "if financial_keys.issubset(namespace):" not in runtime_source


def test_financial_config_no_longer_injects_its_own_staff_price_helpers():
    source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")

    assert "self_service_staff_price: Callable" not in source
    assert "staff_price_required: Callable" not in source
    assert "get_self_service_staff_price = self_service_staff_price" not in source
    assert "is_self_service_staff_price_required = staff_price_required" not in source
