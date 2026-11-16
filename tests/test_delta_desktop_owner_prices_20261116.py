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
    DELTA_ENTERTAINMENT_APPROVAL_REVISION_MARKER,
    DELTA_ENTERTAINMENT_RULE_KEYS,
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
    ("basic_exbar_tech", 1, 1000),
    ("basic_entertain_single", 1, 320),
    ("basic_entertain_single", 2, 600),
    ("basic_entertain_female_single", 1, 320),
    ("basic_entertain_male_single", 2, 600),
    ("basic_one_companion_one_guard_secret", 1, 800),
    ("basic_one_companion_one_guard_topsecret", 1, 900),
    ("basic_tech_secret_single", 1, 450),
    ("basic_tech_secret_single", 2, 850),
    ("basic_tech_topsecret_single", 1, 500),
    ("basic_tech_topsecret_single", 2, 950),
    ("basic_trial_500", 1, 500),
    ("basic_trial_1000", 1, 1000),
    ("basic_bet_1000", 1, 1200),
    ("basic_bet_1500", 1, 1500),
    ("basic_bet_2500", 1, 2400),
    ("basic_oil_fuel", 1, 3000),
    ("basic_oil_satellite", 1, 2000),
    ("basic_oil_all", 1, 4500),
])
def test_owner_prices_use_authoritative_quote_engine(key, count, amount):
    rule = get_rule(key)
    assert key in APPROVED_DELTA_DESKTOP_RULE_KEYS
    assert rule.category == "delta_desktop_basic"
    assert calculate_price(rule, quantity=1, player_count=count).total_amount == amount


@pytest.mark.parametrize("key,guarantee", [
    ("basic_exbar_tech", "850W"),
    ("basic_exbar_tech", "600W + 2"),
    ("basic_trial_500", "850W"),
    ("basic_trial_1000", "1888W"),
    ("basic_tech_secret_single", "777W"),
    ("basic_tech_topsecret_single", "850W"),
    ("basic_one_companion_one_guard_secret", "8殺"),
    ("basic_one_companion_one_guard_topsecret", "7殺"),
    ("basic_bet_1000", "800W"),
    ("basic_bet_1500", "1000W"),
    ("basic_bet_2500", "1200W"),
    ("basic_oil_fuel", "2000W"),
    ("basic_oil_satellite", "1688W"),
    ("basic_oil_all", "3688W"),
])
def test_contractual_guarantees_live_in_source_rules(key, guarantee):
    assert guarantee.replace(" ", "").lower() in get_rule(key).note.replace(" ", "").lower()


def test_approved_dc_price_list_matches_all_six_offers():
    plans = DELTA_DESKTOP_PRICE_LISTS
    for offer, terms in {
        "entertainment": ("320T / H", "600T / H", "10 小時", "+100T"),
        "one_guard": ("800T / H", "900T / H", "8 殺", "7 殺", "2H"),
        "babel_technical": ("1000T / H", "850W", "600W + 2 沙保", "4 沙保"),
        "trial": ("500T", "850W", "1000T", "1888W", "每週", "每月", "打手選圖"),
        "technical": ("450T / H", "850T / H", "500T / H", "950T / H", "777W", "850W"),
        "bet": ("1200T", "800W", "1500T", "1000W", "2400T", "1200W"),
        "oil": ("3000T", "2000W", "2000T", "1688W", "4500T", "3688W"),
    }.items():
        for term in terms:
            assert term in plans[offer]["text"], (offer, term)
    assert "850T / H" not in plans["one_guard"]["text"]
    assert "800T / H" not in plans["technical"]["text"]
    assert "500T　保底 888W" not in plans["trial"]["text"]
    assert "3500W" not in plans["oil"]["text"]


def test_web_and_discord_share_new_trial_selector_and_keep_legacy_aliases():
    dc = get_order_item_details_for_group("delta_desktop_basic", "體驗單")
    web = next(group for group in get_grouped_order_catalog("delta_desktop_basic")
               if group["key"] == "trial")
    assert [r["label"] for r in dc] == ["普通體驗單｜500T（保底850W）", "尊爵體驗單｜1000T（保底1888W）"]
    assert [r["label"] for r in web["variants"]] == ["普通體驗單｜500T（保底850W）", "尊爵體驗單｜1000T（保底1888W）"]
    from services.orders import ORDER_RULE_KEY_BY_LABEL
    assert ORDER_RULE_KEY_BY_LABEL["體驗單 850w"] == "basic_trial_500"
    assert ORDER_RULE_KEY_BY_LABEL["體驗單 888w"] == "basic_trial_500"


def test_manager_stale_overrides_cannot_restore_old_prices_or_guarantees(monkeypatch):
    keys = (
        "basic_exbar_tech", "basic_tech_secret_single", "basic_trial_500",
        "basic_oil_satellite", "basic_bet_2500",
        "basic_one_companion_one_guard_topsecret",
    )
    versions = {}
    for key in keys:
        payload = rule_to_override_payload(get_base_rule(key))
        payload["price"] = 13
        payload["note"] = "舊保底 777W"
        payload["__owner_confirmed_after_canonical"] = True
        payload["__owner_confirmed_delta_desktop_20261116"] = True
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
        assert live.specify_fee_by_role == base.specify_fee_by_role


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
        ("basic_black_tide_entertain", 1, 350),
        ("farm_season_3x3_normal", 1, 5500),
    ):
        assert calculate_price(get_rule(key), quantity=1, player_count=count).total_amount == expected


def test_web_product_card_copy_tracks_latest_source_prices_guarantees():
    groups = {
        item["label"]: item
        for item in get_grouped_order_catalog("delta_desktop_basic")
    }
    expected = {
        "娛樂陪": ("320T/H", "600T/H", "10小時", "+100T"),
        "一陪一護": ("800T/H", "900T/H", "8殺", "7殺"),
        "體驗單": ("500T/單", "850W", "1000T/單", "1888W", "每週", "每月"),
        "技術陪": ("450T/H", "850T/H", "500T/H", "950T/H", "777W", "850W"),
        "絕巴技術陪": ("1000T/H", "850w", "600w+2沙色保險", "4沙色保險"),
        "賭約單": ("1200T/單", "800W", "1500T/單", "1000W", "2400T/單", "1200W"),
        "油鍋單": ("3000T/單", "2000W", "2000T/單", "1688W", "4500T/單", "3688W"),
    }
    for group_name, fragments in expected.items():
        content = groups[group_name]["description"].replace(",", "").replace(" ", "")
        for fragment in fragments:
            assert fragment.replace(",", "").replace(" ", "") in content, (group_name, fragment)


def test_updated_exbar_does_not_modify_fixed_price_or_hourly_specification():
    rule = get_rule("basic_exbar_tech")
    assert rule.price == 1000
    assert rule.pricing_type == "hourly"
    assert rule.allow_specify is True
    assert rule.specify_free_min_units == 2
    assert "850w / 600w + 2 沙色保險 / 4 沙色保險" in rule.note


@pytest.mark.parametrize("key", sorted(DELTA_ENTERTAINMENT_RULE_KEYS))
def test_entertainment_unchanged_old_price_even_with_prior_image_approval(monkeypatch, key):
    """An already-approved 350/650 override may NOT undo the later hold."""
    base = get_base_rule(key)
    payload = rule_to_override_payload(base)
    payload["player_count_prices"] = {"1": 350, "2": 650}
    payload["price"] = 350
    payload["__owner_confirmed_after_canonical"] = True
    payload[DELTA_DESKTOP_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": payload}})

    rule = ORDER_RULES[key]
    assert calculate_price(rule, quantity=1, player_count=1).total_amount == 320
    assert calculate_price(rule, quantity=1, player_count=2).total_amount == 600
    assert rule.specify_fee_default == 100
    assert rule.specify_free_min_units == 2
    assert rule.loyalty_benefits_enabled is True


def test_future_authorized_entertainment_price_update_still_possible(monkeypatch):
    key = "basic_entertain_single"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["player_count_prices"] = {"1": 325, "2": 605}
    payload["price"] = 325
    payload["__owner_confirmed_after_canonical"] = True
    payload[DELTA_ENTERTAINMENT_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": payload}})
    assert calculate_price(ORDER_RULES[key], quantity=1, player_count=1).total_amount == 325
    assert calculate_price(ORDER_RULES[key], quantity=1, player_count=2).total_amount == 605


def test_other_image_price_cards_remain_untouched():
    expected = {
        "one_guard": ("800T / H", "900T / H"),
        "technical": ("450T / H", "850T / H", "500T / H", "950T / H"),
        "trial": ("500T", "850W", "1000T", "1888W"),
        "bet": ("1200T", "1500T", "2400T"),
        "oil": ("3000T", "2000T", "4500T", "3688W"),
        "babel_technical": ("1000T / H", "850W", "600W + 2 沙保"),
    }
    for group, phrases in expected.items():
        for phrase in phrases:
            assert phrase in DELTA_DESKTOP_PRICE_LISTS[group]["text"], (group, phrase)

def test_trial_and_oil_approved_guarantee_labels_parity():
    from services.orders import ORDER_RULE_KEY_BY_LABEL

    approved = {
        "體驗單": (
            ("basic_trial_500", "普通體驗單｜500T（保底850W）", 500),
            ("basic_trial_1000", "尊爵體驗單｜1000T（保底1888W）", 1000),
        ),
        "油鍋單": (
            ("basic_oil_fuel", "火箭燃油（保底2000W）", 3000),
            ("basic_oil_satellite", "GTI衛星通信天線（保底1688W）", 2000),
            ("basic_oil_all", "全包（保底3688W）", 4500),
        ),
    }
    web = {g["label"]: g for g in get_grouped_order_catalog("delta_desktop_basic")}
    for group, expectations in approved.items():
        dc = get_order_item_details_for_group("delta_desktop_basic", group)
        actual_web = web[group]["variants"]
        assert [(v["rule_key"], v["label"]) for v in dc] == [
            (key, label) for key, label, amount in expectations
        ]
        assert [(v["rule_key"], v["label"], v["price"]) for v in actual_web] == list(expectations)
        for key, label, amount in expectations:
            assert calculate_price(get_rule(key), quantity=1).total_amount == amount
            assert ORDER_RULE_KEY_BY_LABEL[get_rule(key).label] == key
    assert "500T（保底850W）" in DELTA_DESKTOP_PRICE_LISTS["trial"]["text"]
    assert "1000T（保底1888W）" in DELTA_DESKTOP_PRICE_LISTS["trial"]["text"]
    for name in ("火箭燃油（保底2000W）", "GTI衛星通信天線（保底1688W）", "全包（保底3688W）"):
        assert name in DELTA_DESKTOP_PRICE_LISTS["oil"]["text"]


def test_fixed_guarantee_label_tracks_authorized_effective_price_and_note():
    from dataclasses import replace
    from services.delta_desktop_guarantee_labels import fixed_guarantee_display_label

    rule = get_base_rule("basic_trial_500")
    revised = replace(rule, price=555, note="普通體驗單｜900W 保底｜每週限一次")
    assert fixed_guarantee_display_label(rule.key, revised, "普通") == "普通體驗單｜555T（保底900W）"
    absent = replace(rule, note="待確認")
    assert fixed_guarantee_display_label(rule.key, absent, "普通") == "普通"
