from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.loyalty_companion_fix_20261029 import calculate_for_rule, extract_player_count


def _rule(key: str, *, price: int, max_players: int = 4):
    return SimpleNamespace(
        key=key,
        price=price,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=max_players,
        price_multiply_player_count=False,
    )


@pytest.mark.parametrize(
    ("rule_key", "base_price", "players", "expected"),
    [
        ("basic_entertain_single", 320, 1, 320),
        ("basic_entertain_single", 320, 2, 300),
        ("basic_entertain_female_single", 320, 2, 300),
        ("basic_entertain_male_single", 320, 2, 300),
        ("basic_mobile_entertain_single", 320, 2, 300),
        ("basic_mobile_entertain_female_single", 320, 2, 300),
        ("basic_mobile_entertain_male_single", 320, 2, 300),
        ("basic_black_tide_entertain", 320, 2, 300),
        ("basic_black_tide_entertain", 320, 3, 300),
        ("basic_black_tide_entertain", 320, 4, 300),
        ("basic_black_tide_tech", 400, 2, 380),
        ("basic_black_tide_tech", 400, 3, 380),
        ("basic_black_tide_tech", 400, 4, 380),
        ("steam_play", 320, 2, 320),
        ("steam_play", 320, 3, 320),
        ("steam_play", 320, 4, 320),
    ],
)
def test_loyalty_reward_uses_selected_tier_per_companion_share(
    rule_key: str, base_price: int, players: int, expected: int
):
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 1}
    assert calculate_for_rule(
        _rule(rule_key, price=base_price), player_count=players, coupon=coupon
    ) == expected


def test_double_companion_half_hour_is_150():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}
    assert calculate_for_rule(
        _rule("basic_entertain_single", price=320, max_players=2),
        player_count=2,
        coupon=coupon,
    ) == 150


def test_linear_multi_seat_price_keeps_one_companion_share():
    rule = SimpleNamespace(
        key="linear_test",
        price=450,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=4,
        price_multiply_player_count=True,
    )
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 1}
    assert calculate_for_rule(rule, player_count=3, coupon=coupon) == 450


@pytest.mark.parametrize(
    "snapshot",
    [
        {"preview": {"quote": {"player_count": 2}}},
        {"input": {"player_count": 2}},
        {"preview": {"selection": {"requested_player_count": 2}}},
        {"order": {"service_player_count": 2}},
        {"data": {"companion_count": 2}},
    ],
)
def test_extract_player_count_supports_old_and_new_snapshots(snapshot):
    row = {"price_snapshot_json": json.dumps(snapshot, ensure_ascii=False)}
    assert extract_player_count(row) == 2


def test_extract_player_count_falls_back_to_one():
    assert extract_player_count({"price_snapshot_json": "{}"}) == 1
