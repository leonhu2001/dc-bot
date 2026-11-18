"""Owner-approved 2026-11-18 Love Delta / Our Love and internal ammo regressions."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.coin_wash_urgent_policy import urgent_fee_for_rule
from services.one_companion_one_guard_payout import is_full_worker_payout_rule
from services.order_rules import (
    FULL_SOURCE_AUTHORITY_RULE_KEYS, HALFCOIN_RECEIVER_ROLES,
    calculate_price, get_base_rule,
)
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_PRICES_BY_RULE, NAMED_SELECTION_KEY,
    calculate_internal_ammo_dump_financials,
    require_ammo_dump_named_selection,
)
from web.app.services.love_delta_service import (
    EVENT_SCORES, EXTRACTION_TIERS, LOVE_DELTA_RULE_KEYS,
    OUR_LOVE_EVENT_SCORES, OUR_LOVE_EXTRACTION_TIERS,
    OUR_LOVE_RULE_KEYS, _plan_from_order,
)
from web.app.services.order_groups import GROUP_SPECS

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("million,amount", [(100, 550), (200, 1080), (300, 1620)])
def test_new_internal_ammo_tiers_named_unnamed_identical(million: int, amount: int):
    key = f"staff_internal_ammo_dump_{million}m"
    rule = get_base_rule(key)
    assert rule.price == amount
    assert rule.category == "staff_internal"
    assert rule.allowed_roles == HALFCOIN_RECEIVER_ROLES
    assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS
    assert is_full_worker_payout_rule(key)
    assert urgent_fee_for_rule(key) == 260
    assert AMMO_DUMP_PRICES_BY_RULE[key] == (amount, amount, amount)
    base_quote = calculate_price(rule, quantity=1)
    for named in (True, False):
        data = {NAMED_SELECTION_KEY: named}
        require_ammo_dump_named_selection(rule, data)
        quote = calculate_internal_ammo_dump_financials(base_quote, data, rule)
        assert quote["customer_pay_amount"] == amount
        assert quote["payout_base_amount"] == amount
        assert quote["store_margin_amount"] == 0
        assert quote["customer_service_payout_amount"] == 0
        assert quote["store_retained_amount"] == 0
    with pytest.raises(ValueError):
        require_ammo_dump_named_selection(rule, {})


def test_500m_internal_ammo_original_naming_margin_is_unchanged():
    key = "staff_internal_ammo_dump_500m"
    rule = get_base_rule(key)
    price = calculate_price(rule, quantity=1)
    for named, pay, staff, cs, retained in (
        (True, 2650, 2650, 0, 0),
        (False, 3000, 2650, 88, 262),
    ):
        quote = calculate_internal_ammo_dump_financials(
            price, {NAMED_SELECTION_KEY: named}, rule
        )
        assert quote["customer_pay_amount"] == pay
        assert quote["payout_base_amount"] == staff
        assert quote["customer_service_payout_amount"] == cs
        assert quote["store_retained_amount"] == retained


def test_internal_discord_groups_preserve_old_500m_and_new_choices():
    groups = {
        group["label"]: group for group in SELF_SERVICE_ORDER_CATALOG["staff_internal"]
    }
    assert "倒子彈｜500M" in groups
    assert "倒子彈｜100M～300M" in groups
    assert [entry["rule_key"] for entry in groups["倒子彈｜100M～300M"]["details"]] == [
        "staff_internal_ammo_dump_100m",
        "staff_internal_ammo_dump_200m",
        "staff_internal_ammo_dump_300m",
    ]


def test_our_love_exact_three_prices_and_shared_checkout_catalog():
    expected = [
        ("fun_our_love_start_75", 2488, 75, 2088),
        ("fun_our_love_start_50", 3688, 50, 3088),
        ("fun_our_love_start_0", 4888, 0, 3688),
    ]
    found = {g["key"]: g for g in GROUP_SPECS}["our_love"]
    assert [k for k, _name in found["variants"]] == [x[0] for x in expected]
    assert found["image"] == "price_lists/delta_fun_our_love_20261118.svg"
    for key, amount, start, guarantee in expected:
        rule = get_base_rule(key)
        assert rule.price == amount
        assert "撤離失敗-10" in rule.note
        assert "千萬撤離額外+3" in rule.note
        assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS
        assert OUR_LOVE_RULE_KEYS[key]["initial_affection"] == start
        assert OUR_LOVE_RULE_KEYS[key]["guarantee_w"] == guarantee
        plan = _plan_from_order({"order_rule_key": key})
        assert plan["mode"] == "our_love"
        assert plan["price"] == amount
    assert len(LOVE_DELTA_RULE_KEYS) == 4
    for plan in LOVE_DELTA_RULE_KEYS.values():
        assert plan["mode"] == "love_delta"


def test_affection_scoring_does_not_cross_game_modes():
    assert OUR_LOVE_EVENT_SCORES["our_kill"][1] == 1
    assert OUR_LOVE_EVENT_SCORES["our_small_red"][1] == 2
    assert OUR_LOVE_EVENT_SCORES["our_big_red"][1] == 5
    assert OUR_LOVE_EVENT_SCORES["our_huge_red"][1] == 10
    assert OUR_LOVE_EVENT_SCORES["our_heart"][1] == 35
    assert OUR_LOVE_EVENT_SCORES["our_boss_kill"][1] == -1
    assert OUR_LOVE_EXTRACTION_TIERS == {0: 0, 1000: 3}
    assert EXTRACTION_TIERS == {0: 0, 300: 4, 600: 8, 900: 12}
    assert EVENT_SCORES["miss_shipment_call"][1] == -2
    assert "寶寶出貨啦" in EVENT_SCORES["miss_shipment_call"][0]
    assert "miss_shipment_call" not in OUR_LOVE_EVENT_SCORES


def test_our_love_url_blue_skin_and_love_delta_existing_link_preserved():
    router = (ROOT / "web/app/routers/love_delta.py").read_text(encoding="utf-8")
    page = (ROOT / "web/app/templates/member_love_delta.html").read_text(encoding="utf-8")
    script = (ROOT / "web/app/static/js/love_delta.js").read_text(encoding="utf-8")
    css = (ROOT / "web/app/static/css/love_delta.css").read_text(encoding="utf-8")
    member = (ROOT / "web/app/templates/member_order_detail.html").read_text(encoding="utf-8")
    assert '@router.get("/me/orders/{order_id}/our-love")' in router
    assert '@router.get("/me/orders/{order_id}/love-delta")' in router
    assert "is-our-love" in page and "ldOurLoveCard" in page
    assert "data-ld-event=\"miss_shipment_call\"" in page
    assert "data-ld-event=\"our_huge_red\"" in page
    assert "const ourLove =" in script
    assert ".ld-page.is-our-love" in css and "#1379bd" in css
    assert 'data.href' in member
    svg = ROOT / "web/app/static/price_lists/delta_fun_our_love_20261118.svg"
    artwork = svg.read_text(encoding="utf-8")
    for value in ("2,488 T", "3,688 T", "4,888 T"):
        assert value in artwork
