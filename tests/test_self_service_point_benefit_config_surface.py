from services import self_service_financials as financials
from services import self_service_point_benefits as point_benefits


def test_financial_config_exposes_point_benefit_binding():
    assert callable(financials.configure_self_service_financials)
    assert callable(point_benefits.configure_self_service_point_benefits)
