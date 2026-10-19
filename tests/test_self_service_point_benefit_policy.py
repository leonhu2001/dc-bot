from types import SimpleNamespace

from services.self_service_point_benefit_policy import (
    check_order_point_benefit_allowed,
)


def _rule(**overrides):
    values = {
        "point_benefits_allowed": True,
        "category": "game",
        "key": "rank_service",
        "label": "技術陪",
        "pricing_type": "hourly",
        "allow_specify": True,
        "loyalty_benefits_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_free_specify_requires_a_selected_staff_member():
    allowed, reason = check_order_point_benefit_allowed(
        _rule(),
        {"kind": "free_specify_fee"},
        {"quantity": 1, "specified_staff_ids": []},
    )
    assert allowed is False
    assert "先指定人員" in reason


def test_free_specify_is_rejected_when_two_hours_are_already_free():
    allowed, reason = check_order_point_benefit_allowed(
        _rule(),
        {"kind": "free_specify_fee"},
        {"quantity": 2, "specified_staff_ids": ["123"]},
    )
    assert allowed is False
    assert "2 小時以上本來就免指定費" in reason


def test_fun_and_trial_orders_keep_point_benefits_disabled():
    allowed, _ = check_order_point_benefit_allowed(
        _rule(category="fun"),
        {"kind": "cash_discount", "amount": 50},
        {},
    )
    assert allowed is False

    allowed, _ = check_order_point_benefit_allowed(
        _rule(key="basic_trial_test", label="體驗單"),
        {"kind": "cash_discount", "amount": 50},
        {},
    )
    assert allowed is False


def test_regular_cash_discount_remains_allowed():
    allowed, reason = check_order_point_benefit_allowed(
        _rule(),
        {"kind": "cash_discount", "amount": 50},
        {},
    )
    assert allowed is True
    assert reason == ""
