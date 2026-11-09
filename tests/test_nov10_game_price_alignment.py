"""2026-11-10 owner image prices must match Bot, Web, and calculation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import quick_order_v2 as quick
from services.quick_order_v2_price_lists import _apex_price_list, _lol_price_list, _steam_price_list
from services.quick_order_v2_production import _public_view_for_channel
from services.game_price_policy_20261023 import GAME_PRICE_OVERRIDES
from services.loyalty_benefits import loyalty_scope_key
from services.order_rules import ORDER_RULES, calculate_price
from services.orders import get_order_item_details_for_group
from web.app.services.order_groups import get_grouped_order_catalog


OWNER_PRICES = {
    # LOL: ARAM/NG per hour, ranked per game.
    "lol_entertain_aram": 350,
    "lol_entertain_ng": 350,
    "lol_entertain_ranked": 280,
    "lol_master_ng": 380,
    "lol_master_ranked": 300,
    "lol_grandmaster_ng": 390,
    "lol_grandmaster_ranked": 350,
    "lol_elite_ng": 400,
    "lol_elite_ranked": 450,
    # APEX: all amounts per player/hour, platinum-or-below rank baseline.
    "apex_entertain_ng": 320,
    "apex_entertain_ranked": 350,
    "apex_diamond_ng": 380,
    "apex_diamond_ranked": 400,
    "apex_master_ng": 400,
    "apex_master_ranked": 450,
    "apex_predator_ng": 500,
    "apex_predator_ranked": 550,
    # Steam: entertainment per player/hour.
    "steam_play": 350,
}


@pytest.mark.parametrize("key,price", OWNER_PRICES.items())
def test_shared_discord_web_price_source_and_legacy_policy_match(key, price):
    rule = ORDER_RULES[key]
    assert rule.price == price
    assert GAME_PRICE_OVERRIDES[key] == price


def test_all_discord_game_catalogs_use_same_prices_as_web():
    for category, label, group in (
        ("lol", "娛樂陪", "lol_entertain"),
        ("lol", "大師陪", "lol_master"),
        ("lol", "宗師陪", "lol_grandmaster"),
        ("lol", "菁英陪", "lol_elite"),
        ("apex", "娛樂陪", "apex_entertain"),
        ("apex", "鑽石陪", "apex_diamond"),
        ("apex", "大師陪", "apex_master"),
        ("apex", "頂獵陪", "apex_predator"),
        ("steam", "娛樂陪", "steam"),
    ):
        discord_rows = get_order_item_details_for_group(category, label)
        web_group = next(
            item for item in get_grouped_order_catalog(category)
            if item["key"] == group
        )
        assert {row["rule_key"] for row in discord_rows} == {
            row["rule_key"] for row in web_group["variants"]
        }
        for row in web_group["variants"]:
            assert row["price"] == ORDER_RULES[row["rule_key"]].price


def test_apex_ranked_tiers_have_correct_per_player_hourly_prices_and_shared_rewards():
    for prefix, base in (
        ("apex_entertain", 350), ("apex_diamond", 400),
        ("apex_master", 450), ("apex_predator", 550),
    ):
        for tier, steps in (("diamond", 1), ("master", 2), ("predator", 3)):
            rule = ORDER_RULES[f"{prefix}_ranked_tier_{tier}"]
            assert rule.price == base + steps * 50
            two_workers = calculate_price(rule, quantity=3, player_count=2)
            assert two_workers.total_amount == (base + steps * 50) * 3 * 2
            assert rule.specify_free_min_units == 2
    baseline = loyalty_scope_key("apex_entertain_ranked")
    for tier in ("diamond", "master", "predator"):
        assert loyalty_scope_key(f"apex_entertain_ranked_tier_{tier}") == baseline


def test_hourly_and_ranked_modes_have_correct_units_and_minimums():
    assert ORDER_RULES["lol_entertain_ranked"].unit_label == "局"
    assert ORDER_RULES["lol_elite_ranked"].unit_label == "局"
    assert ORDER_RULES["steam_play"].unit_label == "H"
    for key in ("lol_teaching_one", "apex_teaching_one"):
        assert ORDER_RULES[key].price == 500
        assert ORDER_RULES[key].min_quantity == 3
    assert ORDER_RULES["lol_sweet_any"].price == 520
    assert ORDER_RULES["steam_sweet_any"].price == 520


def test_prices_in_discord_copy_match_new_poster():
    interaction = SimpleNamespace(guild=None)
    lol = _lol_price_list(interaction)
    apex = _apex_price_list(interaction)
    steam = _steam_price_list(interaction)
    assert all(token in lol for token in (
        "350T / H", "280T / 局", "380T / H", "390T / H", "450T / 局",
        "15 局", "10 小時", "3H 起標",
    ))
    assert all(token in apex for token in (
        "320T / H", "350T / H", "380T / H", "400T / H",
        "450T / H", "500T / H", "550T / H", "白金以下",
        "鑽石 +50T", "大師 +100T", "頂獵 +150T", "3H 起標",
    ))
    assert "一般陪玩" in steam and "350T / H" in steam


def test_public_entry_views_no_longer_include_price_list_button():
    for game in ("delta", "valorant", "lol", "apex", "steam"):
        channel_id = quick.QUICK_ORDER_V2_CHANNELS[game]
        view = _public_view_for_channel(channel_id)
        assert not any(
            str(getattr(child, "custom_id", "") or "").startswith("quick_order_v2_price_list_")
            for child in view.children
        )
    assert len(_public_view_for_channel(quick.QUICK_ORDER_V2_CHANNELS["delta"]).children) == 4
