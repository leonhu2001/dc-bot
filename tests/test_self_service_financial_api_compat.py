from services import self_service_financials as financials


def test_self_service_financial_legacy_exports_remain_available():
    names = (
        "get_order_point_item",
        "get_customer_point_balance_for_order",
        "is_order_point_benefit_allowed_for_rule",
        "_adapt_order_point_benefit_for_rule",
        "get_selected_order_point_benefit",
        "calculate_self_service_financials",
        "apply_self_service_financials_to_order_data",
    )
    for name in names:
        assert callable(getattr(financials, name))
