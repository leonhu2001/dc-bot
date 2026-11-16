"""Owner-approved Delta desktop prices and guarantees: DC/Web/source parity.

New-order prices must be source-owned, old DB overrides must not revive stale
amounts/guarantees, while intentional newly published manager rules still work.
Legacy keys, mobile offers, fulfilment limits, payouts, and order snapshots remain.
"""
from __future__ import annotations

import pytest

from services.order_rules import (
    APPROVED_DELTA_DESKTOP_RULE_KEYS,
    DELTA_DESKTOP_APPROVAL_REVISION_MARKER,
    ORDER_RULES,
    calculate_price,
    get_base_rule,
    get_rule,
    rule_to_override_payload,
)
from services.orders import get_order_item_details_for_group
from services.quick_order_v2_price_lists import DELTA_DESKTOP_PRICE_LISTS
from web.app.services.order_groups import get_grouped_order_catalog


@pytest.mark.parametrize("key,count,amount", [
    ("basic_entertain_single", 1, 350),
    ("basic_entertain_single", 2, 650),
    ("basic_entertain_female_single", 1, 350),
    ("basic_entertain_male_single", 2, 650),
    ("basic_one_companion_one_guard_secret", 1, 800),
    ("basic_one_companion_one_guard_topsecret", 1, 850),
    ("basic_tech_secret_single", 1, 450),
    ("basic_tech_secret_single", 2, 800),
    ("basic_tech_topsecret_single", 1, 500),
    ("basic_tech_topsecret_single", 2, 900),
    ("basic_trial_500", 1, 500),
    ("basic_trial_1000", 1, 1000),
    ("basic_bet_1000", 1, 1300),
    ("basic_bet_1500", 1, 1800),
    ("basic_bet_2500", 1, 2500),
    ("basic_oil_fuel", 1, 2800),
    ("basic_oil_satellite", 1, 2000),
    ("basic_oil_all", 1, 4500),
])
def test_owner_prices_use_authoritative_quote_engine(key, count, amount):
    rule = get_rule(key)
    assert key in APPROVED_DELTA_DESKTOP_RULE_KEYS
    assert rule.category == "delta_desktop_basic"
    assert calculate_price(rule, quantity=1, player_count=count).total_amount == amount


@pytest.mark.parametrize("key,guarantee", [
    ("basic_trial_500", "888W"),
    ("basic_trial_1000", "1888W"),
    ("basic_tech_secret_single", "777W"),
    ("basic_tech_topsecret_single", "850W"),
    ("basic_one_companion_one_guard_secret", "8殺"),
    ("basic_one_companion_one_guard_topsecret", "7殺"),
    ("basic_bet_1000", "800W"),
    ("basic_bet_1500", "1000W"),
    ("basic_bet_2500", "1200W"),
    ("basic_oil_fuel", "2000W"),
    ("basic_oil_satellite", "1500W"),
    ("basic_oil_all", "3500W"),
])
def test_contractual_guarantees_live_in_source_rules(key, guarantee):
    assert guarantee.replace(" ", "").lower() in get_rule(key).note.replace(" ", "").lower()


def test_approved_dc_price_list_matches_all_six_offers():
    plans = DELTA_DESKTOP_PRICE_LISTS
    for offer, terms in {
        "entertainment": ("350T / H", "650T / H", "10 小時", "+100T"),
        "one_guard": ("800T / H", "850T / H", "8 殺", "7 殺", "2H"),
        "trial": ("500T", "888W", "1000T", "1888W", "每週", "每月", "打手選圖"),
        "technical": ("450T / H", "800T / H", "500T / H", "900T / H", "777W", "850W"),
        "bet": ("1300T", "800W", "1800T", "1000W", "2500T", "1200W"),
        "oil": ("2800T", "2000W", "2000T", "1500W", "4500T", "3500W"),
    }.items():
        for term in terms:
            assert term in plans[offer]["text"], (offer, term)
    assert "900T / H" not in plans["one_guard"]["text"]
    assert "950T / H" not in plans["technical"]["text"]
    assert "850W" not in plans["trial"]["text"]
    assert "3688W" not in plans["oil"]["text"]


def test_web_and_discord_share_new_trial_selector_and_keep_legacy_aliases():
    dc = get_order_item_details_for_group("delta_desktop_basic", "體驗單")
    web = next(group for group in get_grouped_order_catalog("delta_desktop_basic")
               if group["key"] == "trial")
    assert [r["label"] for r in dc] == ["普通｜888w", "尊爵｜1888w"]
    assert [r["label"] for r in web["variants"]] == ["普通｜888w", "尊爵｜1888w"]
    from services.orders import ORDER_RULE_KEY_BY_LABEL
    assert ORDER_RULE_KEY_BY_LABEL["體驗單 850w"] == "basic_trial_500"
    assert ORDER_RULE_KEY_BY_LABEL["體驗單 888w"] == "basic_trial_500"


def test_manager_stale_overrides_cannot_restore_old_prices_or_guarantees(monkeypatch):
    keys = (
        "basic_tech_secret_single", "basic_trial_500",
        "basic_oil_satellite", "basic_bet_2500",
        "basic_one_companion_one_guard_topsecret",
    )
    versions = {}
    for key in keys:
        payload = rule_to_override_payload(get_base_rule(key))
        payload["price"] = 13
        payload["note"] = "舊保底 777W"
        payload["__owner_confirmed_after_canonical"] = True
        if payload.get("player_count_prices"):
            payload["player_count_prices"] = {"1": 13, "2": 14}
        versions[key] = {"payload": payload}

    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", versions)
    for key in keys:
        live = ORDER_RULES[key]
        base = get_base_rule(key)
        assert live.price == base.price
        assert live.player_count_prices == base.player_count_prices
        assert live.note == base.note


def test_deliberate_new_manager_price_update_is_not_blocked(monkeypatch):
    key = "basic_tech_secret_single"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["player_count_prices"] = {"1": 455, "2": 805}
    payload["price"] = 455
    payload["__owner_confirmed_after_canonical"] = True
    payload[DELTA_DESKTOP_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": payload}})
    assert calculate_price(ORDER_RULES[key], quantity=1, player_count=2).total_amount == 805


def test_other_games_and_special_services_unchanged():
    for key, count, expected in (
        ("basic_mobile_entertain_single", 2, 600),
        # Mobile tech SKUs were intentionally retired; do not resurrect them.
        ("basic_black_tide_entertain", 1, 320),
        ("farm_season_3x3_normal", 1, 5500),
    ):
        assert calculate_price(get_rule(key), quantity=1, player_count=count).total_amount == expected
