from types import SimpleNamespace

import pytest

from services import order_point_redemption_policy as redemption_policy
from services.point_benefit_catalog import get_point_benefit_item
from services.self_service_point_benefit_policy import check_order_point_benefit_allowed
from services.unified_service_point_policy import (
    calculate_rule_price_service_point_cost,
    is_current_service_bonus,
    is_rule_service_bonus_supported,
)


def _rule(
    *,
    key="test_service",
    label="測試陪玩",
    category="delta_desktop_basic",
    pricing_type="hourly",
    price=320,
    required_staff_count=1,
    point_benefits_allowed=True,
    player_count_prices=None,
):
    return SimpleNamespace(
        key=key,
        label=label,
        category=category,
        pricing_type=pricing_type,
        price=price,
        required_staff_count=required_staff_count,
        point_benefits_allowed=point_benefits_allowed,
        player_count_prices=dict(player_count_prices or {}),
        allow_specify=True,
    )


def _benefit(*, tier="technical", seats=1, size="small", cost=999):
    return {
        "key": f"test_{tier}_{seats}_{size}",
        "kind": "service_bonus",
        "service_tier": tier,
        "seat_count": seats,
        "bonus_size": size,
        "cost": cost,
        "name": "測試服務加贈",
    }


def test_delta_320_hourly_uses_formal_price_for_both_reward_sizes():
    rule = _rule(price=320)
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(size="small")
    ) == 80
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(size="large")
    ) == 150


def test_delta_450_hourly_rounds_each_one_seat_reward_up_to_ten():
    rule = _rule(price=450)
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(size="small")
    ) == 120
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(size="large")
    ) == 210


def test_non_linear_multi_seat_checkout_does_not_distort_service_point_cost():
    rule = _rule(
        key="basic_black_tide_entertain",
        label="黑潮爆破｜娛樂陪",
        price=320,
        required_staff_count="player_count",
        player_count_prices={1: 320, 2: 600, 3: 900, 4: 1200},
    )
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(tier="entertainment", seats=4, size="small"), player_count=4
    ) == 320
    assert calculate_rule_price_service_point_cost(
        rule=rule, benefit=_benefit(tier="entertainment", seats=4, size="large"), player_count=4
    ) == 600


@pytest.mark.parametrize(
    ("key", "label", "category"),
    [
        ("lol_teaching_one", "英雄聯盟｜教學單｜1對1", "lol"),
        ("valorant_sweet_any", "特戰英豪｜甜蜜單｜不限", "valorant"),
        ("steam_service", "Steam 陪玩", "steam"),
    ],
)
def test_formal_products_that_cannot_extend_service_stay_disabled(key, label, category):
    rule = _rule(key=key, label=label, category=category, price=500)
    assert is_rule_service_bonus_supported(rule) is False


def test_fixed_or_point_disabled_products_cannot_receive_service_reward():
    assert is_rule_service_bonus_supported(_rule(pricing_type="fixed", price=500)) is False
    assert is_rule_service_bonus_supported(_rule(point_benefits_allowed=False)) is False


def test_legacy_service_alias_keeps_snapshot_semantics():
    legacy = get_point_benefit_item("tech_service_small")
    assert legacy
    assert is_current_service_bonus(legacy) is False
    assert int(legacy["cost"]) == 110


def test_payment_rejects_current_service_reward_on_unsupported_product(monkeypatch):
    item = _benefit(tier="technical", seats=1, size="small", cost=1)
    rule = _rule(key="lol_teaching_one", label="英雄聯盟｜教學單｜1對1", category="lol", price=500)
    monkeypatch.setattr(redemption_policy, "_resolve_order_rule", lambda data: rule)
    monkeypatch.setattr(redemption_policy, "get_point_benefit_item", lambda key: item)

    with pytest.raises(ValueError, match="不支援加時／加局"):
        redemption_policy.get_pending_point_benefit_info(
            {"point_benefit_key": item["key"], "point_benefit_cost": 1},
            point_item_lookup=lambda key: item,
            to_int=lambda value, default=0: int(value if value is not None else default),
        )


def test_payment_recalculates_eligible_service_reward_instead_of_trusting_snapshot(monkeypatch):
    item = _benefit(tier="technical", seats=1, size="large", cost=1)
    rule = _rule(key="basic_tech_topsecret_single", label="技術陪〈端遊〉｜絕密", price=450)
    monkeypatch.setattr(redemption_policy, "_resolve_order_rule", lambda data: rule)
    monkeypatch.setattr(redemption_policy, "get_point_benefit_item", lambda key: item)
    monkeypatch.setattr(redemption_policy, "is_service_bonus_allowed_for_rule", lambda *args, **kwargs: True)

    data = {"point_benefit_key": item["key"], "point_benefit_cost": 99999}
    result = redemption_policy.get_pending_point_benefit_info(
        data,
        point_item_lookup=lambda key: item,
        to_int=lambda value, default=0: int(value if value is not None else default),
    )
    assert result["cost"] == 210
    assert data["point_benefit_cost"] == 210


def test_payment_fails_closed_when_current_service_reward_has_no_formal_rule(monkeypatch):
    item = _benefit(tier="technical", seats=1, size="small")
    monkeypatch.setattr(redemption_policy, "_resolve_order_rule", lambda data: None)
    monkeypatch.setattr(redemption_policy, "get_point_benefit_item", lambda key: item)

    with pytest.raises(ValueError, match="找不到正式商品規則"):
        redemption_policy.get_pending_point_benefit_info(
            {"point_benefit_key": item["key"]},
            point_item_lookup=lambda key: item,
            to_int=lambda value, default=0: int(value if value is not None else default),
        )


def test_cash_point_benefit_is_not_disabled_just_because_service_extension_is_disabled(monkeypatch):
    rule = _rule(key="lol_teaching_one", label="英雄聯盟｜教學單｜1對1", category="lol")
    monkeypatch.setattr(
        "services.self_service_point_benefit_policy.get_manager_point_benefit_setting",
        lambda key: None,
    )
    allowed, reason = check_order_point_benefit_allowed(
        rule,
        {"key": "discount_50", "kind": "cash_discount", "amount": 50},
        {},
    )
    assert allowed is True, reason
