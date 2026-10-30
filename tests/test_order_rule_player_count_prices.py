import json
from dataclasses import replace

import pytest

from services.order_rules import (
    build_custom_rule,
    build_order_rule_snapshot,
    calculate_price,
    rule_to_override_payload,
)


def _custom_payload(**changes):
    payload = {
        "label": "自訂多人陪玩",
        "pricing_type": "hourly",
        "price": 320,
        "unit_label": "H",
        "allowed_roles": ["male_companion", "female_companion"],
        "required_staff_count": "player_count",
        "player_count_enabled": True,
        "min_player_count": 1,
        "max_player_count": 4,
        "price_multiply_player_count": False,
        "player_count_prices": {"1": 320, "2": 600, "3": 850, "4": 1000},
    }
    payload.update(changes)
    return payload


def test_custom_player_count_prices_normalize_json_keys_and_drive_price():
    rule = build_custom_rule("custom_multi_test", "custom", _custom_payload())

    assert rule.player_count_prices == {1: 320, 2: 600, 3: 850, 4: 1000}
    assert calculate_price(rule, quantity=1, player_count=3).base_amount == 850


def test_custom_player_count_prices_survive_json_round_trip():
    original = build_custom_rule("custom_multi_test", "custom", _custom_payload())
    persisted = json.loads(json.dumps(rule_to_override_payload(original), ensure_ascii=False))
    restored = build_custom_rule("custom_multi_test", "custom", persisted)

    assert restored.player_count_prices == original.player_count_prices
    assert calculate_price(restored, quantity=2, player_count=2).base_amount == 1200


def test_legacy_custom_payload_without_player_count_prices_still_loads():
    payload = _custom_payload(price_multiply_player_count=True)
    payload.pop("player_count_prices")

    rule = build_custom_rule("custom_multi_legacy", "custom", payload)

    assert rule.player_count_prices == {}
    assert calculate_price(rule, quantity=1, player_count=2).base_amount == 640


def test_explicit_player_count_prices_take_precedence_over_multiplier_mode():
    rule = build_custom_rule(
        "custom_multi_precedence",
        "custom",
        _custom_payload(price_multiply_player_count=True),
    )

    assert calculate_price(rule, quantity=1, player_count=2).base_amount == 600


@pytest.mark.parametrize(
    "prices",
    [
        {"1": 320, "2": 600, "4": 1000},
        {"1": 320, "2": 600, "3": 850, "4": 0},
        {"0": 100, "1": 320, "2": 600, "3": 850, "4": 1000},
        {"1": 320, "2": 600, "3": 850, "4": 1000, "5": 1200},
    ],
)
def test_invalid_player_count_price_tables_are_rejected(prices):
    with pytest.raises((RuntimeError, ValueError)):
        build_custom_rule(
            "custom_multi_invalid",
            "custom",
            _custom_payload(player_count_prices=prices),
        )


def test_duplicate_normalized_player_count_keys_are_rejected():
    with pytest.raises(ValueError, match="重複定義"):
        build_custom_rule(
            "custom_multi_duplicate",
            "custom",
            _custom_payload(player_count_prices={1: 320, "1": 330, 2: 600, 3: 850, 4: 1000}),
        )


def test_order_rule_snapshot_keeps_original_multi_seat_price_table():
    original = build_custom_rule("custom_multi_snapshot", "custom", _custom_payload())
    snapshot = build_order_rule_snapshot(
        original,
        quantity=1,
        player_count=2,
        required_staff_count=2,
    )
    changed = replace(original, player_count_prices={1: 500, 2: 900, 3: 1200, 4: 1500})

    assert snapshot["rule"]["player_count_prices"] == {
        "1": 320,
        "2": 600,
        "3": 850,
        "4": 1000,
    }
    assert snapshot["resolved"]["player_count"] == 2
    assert calculate_price(changed, quantity=1, player_count=2).base_amount == 900
