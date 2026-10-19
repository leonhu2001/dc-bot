from services import self_service_point_benefits as point_benefits


def test_canonical_point_benefit_catalog_is_available_before_runtime_binding():
    assert isinstance(point_benefits.ORDER_POINT_BENEFIT_SPECS, dict)
    assert isinstance(point_benefits.POINT_REDEEM_ITEMS_BY_KEY, dict)
