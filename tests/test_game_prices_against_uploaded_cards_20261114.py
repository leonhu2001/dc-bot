"""Canonical prices copied from the four owner-supplied 2026-11-14 image cards.

This deliberately tests the *actual* Discord/Web OrderRule -> calculate_price
path, not only a duplicated price-list string.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.order_rules import (
    APPROVED_GAME_PRICE_RULE_KEYS, ORDER_RULES, calculate_price, get_base_rule,
)
from services.orders import get_order_item_details_for_group
from services import quick_order_v2, quick_order_v2_price_lists
from web.app.services.order_groups import get_grouped_order_catalog


APPROVED_PRICE = {
    # APEX: every rate is per person per hour.
    "apex_entertain_ng": 320,
    "apex_entertain_ranked": 350,
    "apex_diamond_ng": 380,
    "apex_diamond_ranked": 400,
    "apex_master_ng": 400,
    "apex_master_ranked": 450,
    "apex_predator_ng": 500,
    "apex_predator_ranked": 550,
    # LoL: ARAM/NG are hours, ranked is per game.
    "lol_entertain_aram": 350,
    "lol_entertain_ng": 350,
    "lol_entertain_ranked": 280,
    "lol_master_ng": 380,
    "lol_master_ranked": 300,
    "lol_grandmaster_ng": 390,
    "lol_grandmaster_ranked": 350,
    "lol_elite_ng": 400,
    "lol_elite_ranked": 430,
    # Three existing LoL technical ARAM SKU aliases are hourly, same as NG.
    "lol_master_aram": 380,
    "lol_grandmaster_aram": 390,
    "lol_elite_aram": 400,
    # VALORANT: NG hours, ranked games.
    "valorant_entertain_ng": 350,
    "valorant_entertain_ranked": 280,
    "valorant_ascendant_ng": 330,
    "valorant_ascendant_ranked": 300,
    "valorant_immortal_ng": 350,
    "valorant_immortal_ranked": 330,
    "valorant_radiant_ng": 380,
    "valorant_radiant_ranked": 370,
    "steam_play": 350,
}


@pytest.mark.parametrize("key,unit_price", APPROVED_PRICE.items())
def test_current_skus_have_correct_unit_price_and_live_quote(key, unit_price):
    rule = ORDER_RULES[key]
    assert rule.price == unit_price
    assert calculate_price(rule, quantity=1, player_count=1).base_amount == unit_price
    assert calculate_price(rule, quantity=2, player_count=2).base_amount == 4 * unit_price
    assert rule.pricing_type == ("game" if key.startswith(("lol_", "valorant_")) and key.endswith("_ranked") else "hourly")
    assert key in APPROVED_GAME_PRICE_RULE_KEYS


def test_old_manager_override_prices_cannot_resurrect_after_deployment(monkeypatch):
    key = "lol_entertain_aram"
    base = get_base_rule(key)
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {
        key: {"payload": {"price": 300}},
        "apex_master_ng": {"payload": {"price": 480}},
        "steam_play": {"payload": {"price": 320}},
    })
    assert ORDER_RULES[key].price == 350
    assert ORDER_RULES["apex_master_ng"].price == 400
    assert ORDER_RULES["steam_play"].price == 350
    assert base.price == 350


def test_lol_aram_label_and_discord_sections_follow_live_rules():
    assert "ARAM" in [
        row["label"] for row in get_order_item_details_for_group("lol", "娛樂陪")
    ]
    interaction = SimpleNamespace(guild=None)
    for game in ("apex", "lol", "valorant", "steam"):
        channel_id = quick_order_v2.QUICK_ORDER_V2_CHANNELS[game]
        sections = quick_order_v2_price_lists._game_price_list_sections(interaction, channel_id)
        assert set(sections) == (
            {"entertainment", "sweet"} if game == "steam"
            else {"entertainment", "technical", "sweet", "teaching"}
        )
        assert "指定陪玩" in sections["entertainment"]
        if game != "steam":
            assert "白金以下" in sections["entertainment"]
            assert "每往上一階 +50T" in sections["entertainment"]
    lol = quick_order_v2_price_lists._game_price_list_sections(
        interaction, quick_order_v2.QUICK_ORDER_V2_CHANNELS["lol"]
    )
    assert "350T / H" in lol["entertainment"]
    assert "280T / 局" in lol["entertainment"]
    assert "390T / H" in lol["technical"]
    assert "430T / 局" in lol["technical"]


def test_website_apex_description_is_from_current_order_rules():
    groups = {g["key"]: g for g in get_grouped_order_catalog("apex")}
    for name in ("entertain", "diamond", "master", "predator"):
        pair = f"apex_{name}"
        ng = APPROVED_PRICE[pair + "_ng"]
        ranked = APPROVED_PRICE[pair + "_ranked"]
        assert f"NG {ng}T/人/H、積分 {ranked}T/人/H" in groups[pair]["description"]


def test_screenshot_lol_aram_vip_96_percent_uses_new_350_price(monkeypatch):
    """The user's old Discord panel showed 300 -> 288; new quote must be 350 -> 336."""
    from services import self_service_financials as finance
    from services import self_service_loyalty_discount as loyalty

    monkeypatch.setattr(finance, "_to_int", lambda v, default=None: int(v) if v not in (None, "") else default)
    monkeypatch.setattr(
        finance, "_resolve_self_service_discount_rate",
        lambda rule, data: (96.0, "自動VIP優惠", "vip", "鑽石魔丸"),
    )
    monkeypatch.setattr(finance, "get_selected_order_point_benefit", lambda data, rule: None)
    monkeypatch.setattr(finance, "calculate_one_seat_service_bonus_value", lambda **kwargs: 0)
    monkeypatch.setattr(finance, "resolve_vip_monthly_cash_discount", lambda data, **kwargs: (None, 0))
    monkeypatch.setattr(finance, "build_vip_monthly_discount_result", lambda *args: {})
    monkeypatch.setattr(finance, "build_vip_monthly_discount_note", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        loyalty, "resolve_self_service_loyalty_discount",
        lambda **kwargs: {
            "service_value": 0, "discount_amount": 0,
            "coupon_id": None, "coupon_title": "",
            "coupon": None, "service_note": "",
        },
    )

    def allocate(*, after_percent_amount, fixed_discount_amount,
                 additional_store_discount_amount=0,
                 extra_customer_charge_amount=0):
        return SimpleNamespace(
            payout_base_amount=after_percent_amount + extra_customer_charge_amount,
            customer_pay_amount=max(0, after_percent_amount - fixed_discount_amount
                                    - additional_store_discount_amount
                                    + extra_customer_charge_amount),
            store_absorbed_amount=fixed_discount_amount + additional_store_discount_amount,
        )

    monkeypatch.setattr(finance, "allocate_store_absorbed_fixed_discount", allocate)
    rule = ORDER_RULES["lol_entertain_aram"]
    price = calculate_price(rule, quantity=1, player_count=1)
    result = finance.calculate_self_service_financials(
        rule, price, {"quantity": 1, "player_count": 1}
    )
    assert price.base_amount == 350
    assert result["rule_original_amount"] == 350
    assert result["discount_rate_percent"] == 96.0
    assert result["customer_pay_amount"] == 336
    assert result["payout_base_amount"] == 336
