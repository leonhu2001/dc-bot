"""2026-11-14 owner price cards are the only source for public washing rates.

Assert the same ten SKUs, amounts, and worker-only express accounting on Discord
and the Web. Legacy manual entries must stay historical, never new checkout.
"""
from __future__ import annotations

import json

import pytest

from services.order_rules import (
    ORDER_RULES, PUBLIC_COIN_WASH_VARIANTS,
    PUBLIC_COIN_WASH_PRICE_RULE_KEYS, get_base_rule,
    get_allowed_role_ids, HALFCOIN_RECEIVER_ROLE_ID,
)
from services.orders import get_order_item_details_for_group
from services.coin_wash_urgent_policy import urgent_fee_from_price_snapshot
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.public_checkout import build_public_quote
from web.app.services.checkout_preview import calculate_checkout_financials

EXPECTED = {
    "farm_coin_wash_car_100m": 700,
    "farm_coin_wash_car_200m": 1400,
    "farm_coin_wash_car_500m": 3250,
    "farm_coin_wash_car_1000m": 6100,
    "farm_coin_wash_ammo_dump_100m": 800,
    "farm_coin_wash_ammo_dump_200m": 1500,
    "farm_coin_wash_ammo_dump_300m": 2100,
    "farm_coin_wash_ammo_dump_500m": 3300,
    "farm_coin_wash_ammo_dump_1000m": 6400,
    "farm_coin_wash_ammo_dump_2000m": 11500,
}


def _catalog_dict():
    return {
        variant["rule_key"]: variant
        for group in get_grouped_order_catalog("farm")
        if group["key"] == "coin_wash"
        for variant in group["variants"]
    }


def test_owner_price_cards_are_identical_for_dc_and_web():
    assert set(EXPECTED) == PUBLIC_COIN_WASH_PRICE_RULE_KEYS
    assert len(PUBLIC_COIN_WASH_VARIANTS) == 10
    web = _catalog_dict()
    dc = {
        item["rule_key"]: item
        for item in get_order_item_details_for_group("farm", "對外洗幣")
    }
    assert set(web) == set(dc) == set(EXPECTED)

    for key, expected in EXPECTED.items():
        rule = ORDER_RULES[key]
        assert rule.price == expected
        assert get_base_rule(key).price == expected
        assert get_allowed_role_ids(rule) == [HALFCOIN_RECEIVER_ROLE_ID]
        assert rule.pricing_type == "fixed"
        assert rule.min_quantity == rule.max_quantity == 1
        assert rule.vip_discount_allowed is False
        assert rule.point_benefits_allowed is False
        assert web[key]["price"] == expected
        assert web[key]["pricing_type"] == "fixed"
        assert web[key]["price_text"] == f"{expected:,}T"
        assert f"{expected:,}T" in dc[key]["label"]
        assert build_public_quote(rule_key=key)["customer_pay_amount"] == expected
        assert build_public_quote(rule_key=key)["manual_quote"] is False


@pytest.mark.parametrize("key,expected", sorted(EXPECTED.items()))
def test_wash_urgent_in_web_quote_is_customer_paid_and_worker_only(key, expected):
    quote = build_public_quote(
        rule_key=key, quantity=1,
        customer_adjustments=["coin_wash_urgent"],
    )
    assert quote["base_amount"] == expected
    assert quote["adjustment_amount"] == 280
    assert quote["customer_pay_amount"] == expected + 280
    assert quote["urgent_fee_amount"] == 280
    finance = calculate_checkout_financials(
        service_amount=expected,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None, wallet_balance=0, use_wallet=False,
        urgent_fee_amount=quote["urgent_fee_amount"],
    )
    assert finance["original_amount"] == expected + 280
    assert finance["customer_pay_amount"] == expected + 280
    assert finance["payout_base_amount"] == expected
    assert finance["store_absorbed_amount"] == 0
    snapshot = {"order_rule_key": key, "urgent_fee_amount": 280}
    assert urgent_fee_from_price_snapshot(json.dumps(snapshot)) == 280
    assert urgent_fee_from_price_snapshot(
        {**snapshot, "urgent_fee_amount": 281}
    ) == 0


def test_urgent_fee_remains_non_discountable_and_wallet_compatible():
    finance = calculate_checkout_financials(
        service_amount=700, vip_pay_rate=96, specify_fee=0,
        point_item=None, wallet_balance=800, use_wallet=True,
        urgent_fee_amount=280,
    )
    assert finance["service_after_vip"] == 672
    assert finance["urgent_fee_amount"] == 280
    assert finance["subtotal_before_wallet"] == 952
    assert finance["wallet_use_amount"] == 800
    assert finance["remaining_pay_amount"] == 152
    assert finance["payout_base_amount"] == 672


def test_unsupported_urgent_and_retired_direct_requests_are_rejected():
    with pytest.raises(ValueError, match="不支援洗幣加急"):
        build_public_quote(
            rule_key="farm_aw_collision_1_100", quantity=1,
            customer_adjustments=["coin_wash_urgent"],
        )
    for key in (
        "farm_halfcoin_120m", "farm_halfcoin_360m",
        "farm_coin_wash_car", "farm_coin_wash_ammo_dump",
    ):
        with pytest.raises(ValueError, match="已停止提供新訂單"):
            build_public_quote(rule_key=key)


def test_manager_override_cannot_put_old_manual_rate_back(monkeypatch):
    key = "farm_coin_wash_car_100m"
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {
        key: {"payload": {
            "price": 0, "pricing_type": "manual",
            "allowed_roles": ["male_companion"],
        }}
    })
    rule = ORDER_RULES[key]
    assert rule.price == 700
    assert rule.pricing_type == "fixed"
    assert get_allowed_role_ids(rule) == [HALFCOIN_RECEIVER_ROLE_ID]
