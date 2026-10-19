from pathlib import Path

from services import self_service_financials as financials
from services import self_service_point_benefits as point_benefits


def test_point_benefit_policy_is_physically_extracted_from_financial_engine():
    financial_source = Path("services/self_service_financials.py").read_text(encoding="utf-8")
    point_source = Path("services/self_service_point_benefits.py").read_text(encoding="utf-8")

    assert "def get_order_point_item" not in financial_source
    assert "def get_customer_point_balance_for_order" not in financial_source
    assert "def is_order_point_benefit_allowed_for_rule" not in financial_source
    assert "def get_selected_order_point_benefit" not in financial_source

    assert "def get_order_point_item" in point_source
    assert "def get_customer_point_balance_for_order" in point_source
    assert "def is_order_point_benefit_allowed_for_rule" in point_source
    assert "def get_selected_order_point_benefit" in point_source
    assert "import bot" not in point_source
    assert "from bot import" not in point_source


def test_financial_runtime_keeps_legacy_point_benefit_exports():
    assert financials.get_order_point_item is point_benefits.get_order_point_item
    assert (
        financials.get_customer_point_balance_for_order
        is point_benefits.get_customer_point_balance_for_order
    )
    assert (
        financials.is_order_point_benefit_allowed_for_rule
        is point_benefits.is_order_point_benefit_allowed_for_rule
    )
    assert (
        financials.get_selected_order_point_benefit
        is point_benefits.get_selected_order_point_benefit
    )


def test_financial_config_owns_point_benefit_startup_binding():
    source = Path("services/self_service_financials.py").read_text(encoding="utf-8")
    assert "configure_self_service_point_benefits(" in source
