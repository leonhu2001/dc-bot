from services import self_service_financials as financials
from services.aw_collision_catalog import AW_RULE_KEYS
from services.order_rules import ORDER_RULES


def test_aw_staff_price_is_optional_not_required():
    for key in AW_RULE_KEYS:
        assert financials.is_self_service_staff_price_required(ORDER_RULES[key]) is False


def test_aw_rules_reject_vip_points_and_loyalty():
    for key in AW_RULE_KEYS:
        rule = ORDER_RULES[key]
        assert rule.vip_discount_allowed is False
        assert rule.point_benefits_allowed is False
        assert rule.loyalty_benefits_enabled is False
