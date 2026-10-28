from __future__ import annotations

import services  # noqa: F401 - install production runtime policies

from services.order_rules import ORDER_RULES
from services.point_benefit_catalog import (
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
)
from services.self_service_point_benefit_policy import check_order_point_benefit_allowed
from web.app.services import checkout_preview
from web.app.services.point_benefit_policy_bridge import install_shared_point_benefit_policy


install_shared_point_benefit_policy()


def _benefit(key: str) -> dict:
    item = get_point_benefit_item(key)
    assert item is not None
    return item


def _assert_allowed(rule_key: str, benefit_key: str, player_count: int) -> dict:
    rule = ORDER_RULES[rule_key]
    benefit = _benefit(benefit_key)
    allowed, reason = check_order_point_benefit_allowed(
        rule,
        benefit,
        {"quantity": 1, "player_count": player_count, "specified_staff_ids": []},
    )
    assert allowed is True, reason
    return adapt_point_benefit_for_rule(rule, benefit)


def test_valorant_entertainment_point_rewards_support_four_companions() -> None:
    small = _benefit("entertain_quad_service_small")
    large = _benefit("entertain_quad_service_large")
    assert small["cost"] == 320
    assert large["cost"] == 560

    hourly = _assert_allowed("valorant_entertain_ng", "entertain_quad_service_small", 4)
    assert hourly["kind"] == "extra_hours"
    assert hourly["hours"] == 0.5
    assert "4 位陪玩同步加贈" in hourly["summary"]

    ranked = _assert_allowed("valorant_entertain_ranked", "entertain_quad_service_large", 4)
    assert ranked["kind"] == "extra_games"
    assert ranked["games"] == 2
    assert "4 位陪玩同步加贈" in ranked["summary"]


def test_lol_entertainment_and_rank_point_rewards_use_selected_count() -> None:
    entertainment = _assert_allowed("lol_entertain_ranked", "entertain_triple_service_small", 3)
    assert _benefit("entertain_triple_service_small")["cost"] == 240
    assert entertainment["kind"] == "extra_games"
    assert entertainment["games"] == 1

    technical = _assert_allowed("lol_master_ng", "tech_triple_service_large", 3)
    assert _benefit("tech_triple_service_large")["cost"] == 540
    assert technical["kind"] == "extra_hours"
    assert technical["hours"] == 1.0
    assert "3 位陪玩同步加贈" in technical["summary"]


def test_apex_point_rewards_support_two_companions_for_hourly_modes() -> None:
    entertainment = _assert_allowed("apex_entertain_ranked", "entertain_double_service_large", 2)
    assert _benefit("entertain_double_service_large")["cost"] == 280
    assert entertainment["kind"] == "extra_hours"
    assert entertainment["hours"] == 1.0

    technical = _assert_allowed("apex_master_ng", "tech_double_service_small", 2)
    assert _benefit("tech_double_service_small")["cost"] == 200
    assert technical["kind"] == "extra_hours"
    assert technical["hours"] == 0.5


def test_service_reward_rejects_wrong_companion_count() -> None:
    rule = ORDER_RULES["lol_entertain_ng"]
    allowed, reason = check_order_point_benefit_allowed(
        rule,
        _benefit("entertain_double_service_small"),
        {"quantity": 1, "player_count": 3, "specified_staff_ids": []},
    )
    assert allowed is False
    assert "陪玩人數" in reason


def test_web_uses_same_game_point_reward_policy() -> None:
    cases = (
        ("valorant_entertain_ng", "entertain_quad_service_small", 4),
        ("valorant_radiant_ranked", "tech_quad_service_large", 4),
        ("lol_entertain_ranked", "entertain_triple_service_small", 3),
        ("lol_master_ng", "tech_triple_service_large", 3),
        ("apex_entertain_ranked", "entertain_double_service_large", 2),
        ("apex_master_ng", "tech_double_service_small", 2),
    )
    for rule_key, benefit_key, player_count in cases:
        status = checkout_preview.point_item_status(
            rule_key=rule_key,
            point_item_key=benefit_key,
            point_balance=9999,
            quantity=1,
            has_specified_staff=False,
            player_count=player_count,
        )
        assert status["allowed"] is True, (rule_key, benefit_key, status)
