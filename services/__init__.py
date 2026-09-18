"""Shared runtime pricing overrides for both Discord bot and web.

This package-level patch keeps the existing order-rule catalog intact while applying
current storefront prices in one place. Existing orders remain protected because
orders persist a rule snapshot at creation time.
"""

from __future__ import annotations

from dataclasses import replace
import importlib.util

from . import order_rules as _order_rules


# 2026-09-16 confirmed storefront prices.
_RULE_UPDATES: dict[str, dict] = {
    # Delta Force
    "basic_entertain_single": {"price": 320},
    "basic_entertain_double": {"price": 600},
    "basic_tech_secret_single": {"price": 400},
    "basic_tech_secret_double": {"price": 750},
    "basic_tech_topsecret_single": {"price": 450},
    "basic_tech_topsecret_double": {"price": 850},
    "basic_exbar_tech": {
        "price": 1000,
        "note": "保底三選一：800w / 500w + 2 沙色保險 / 4 沙色保險",
    },
    "basic_sweet_single": {"price": 450},
    "basic_trial_500": {"price": 450},
    "basic_trial_1000": {"price": 900},
    "basic_bet_1000": {"price": 800},
    "basic_bet_1500": {"price": 1200},
    "basic_bet_2500": {"price": 1500},
    "basic_oil_fuel": {"price": 2600},
    "basic_oil_satellite": {"price": 1800},
    "basic_oil_all": {"price": 4000},

    # Steam
    "steam_play": {"price": 320},

    # VALORANT: NG is hourly; ranked remains per game.
    "valorant_entertain_ng": {"price": 300, "pricing_type": "hourly", "unit_label": "H"},
    "valorant_entertain_ranked": {"price": 250, "pricing_type": "game", "unit_label": "局"},
    "valorant_ascendant_ng": {"price": 340, "pricing_type": "hourly", "unit_label": "H"},
    "valorant_ascendant_ranked": {"price": 300, "pricing_type": "game", "unit_label": "局"},
    "valorant_immortal_ng": {"price": 360, "pricing_type": "hourly", "unit_label": "H"},
    "valorant_immortal_ranked": {"price": 350, "pricing_type": "game", "unit_label": "局"},
    "valorant_radiant_ng": {"price": 400, "pricing_type": "hourly", "unit_label": "H"},
    "valorant_radiant_ranked": {"price": 400, "pricing_type": "game", "unit_label": "局"},

    # League of Legends: ARAM/NG are hourly; ranked remains per game.
    "lol_entertain_aram": {"price": 300, "pricing_type": "hourly", "unit_label": "H"},
    "lol_entertain_ng": {"price": 300, "pricing_type": "hourly", "unit_label": "H"},
    "lol_entertain_ranked": {"price": 250, "pricing_type": "game", "unit_label": "局"},
    "lol_master_ng": {"price": 340, "pricing_type": "hourly", "unit_label": "H"},
    "lol_master_ranked": {"price": 300, "pricing_type": "game", "unit_label": "局"},
    "lol_grandmaster_ng": {"price": 360, "pricing_type": "hourly", "unit_label": "H"},
    "lol_grandmaster_ranked": {"price": 350, "pricing_type": "game", "unit_label": "局"},
    "lol_elite_ng": {"price": 400, "pricing_type": "hourly", "unit_label": "H"},
    "lol_elite_ranked": {"price": 400, "pricing_type": "game", "unit_label": "局"},

    # APEX (hourly). Ranked variants are always +50T/H.
    "apex_entertain_platinum": {"price": 300},
    "apex_entertain_platinum_ranked": {"price": 350},
    "apex_entertain_diamond": {"price": 330},
    "apex_entertain_diamond_ranked": {"price": 380},
    "apex_entertain_master": {"price": 350},
    "apex_entertain_master_ranked": {"price": 400},

    "apex_diamond_platinum": {"price": 360},
    "apex_diamond_platinum_ranked": {"price": 410},
    "apex_diamond_diamond": {"price": 400},
    "apex_diamond_diamond_ranked": {"price": 450},

    "apex_master_platinum": {"price": 420},
    "apex_master_platinum_ranked": {"price": 470},
    "apex_master_diamond": {"price": 460},
    "apex_master_diamond_ranked": {"price": 510},
    "apex_master_master": {"price": 500},
    "apex_master_master_ranked": {"price": 550},

    "apex_predator_platinum": {"price": 500},
    "apex_predator_platinum_ranked": {"price": 550},
    "apex_predator_diamond": {"price": 550},
    "apex_predator_diamond_ranked": {"price": 600},
    "apex_predator_master": {"price": 600},
    "apex_predator_master_ranked": {"price": 650},
}


def _replace_rule(rule_key: str, **changes) -> None:
    rule = _order_rules.ORDER_RULES.get(rule_key)
    if rule is None:
        raise RuntimeError(f"missing pricing rule: {rule_key}")
    _order_rules.ORDER_RULES[rule_key] = replace(rule, **changes)


for _rule_key, _changes in _RULE_UPDATES.items():
    _replace_rule(_rule_key, **_changes)


# All ordinary 150T specify fees become 100T. Zero-fee special products stay zero.
for _rule_key, _rule in list(_order_rules.ORDER_RULES.items()):
    _changes: dict = {}

    if int(getattr(_rule, "specify_fee_default", 0) or 0) == 150:
        _changes["specify_fee_default"] = 100

    _role_fees = dict(getattr(_rule, "specify_fee_by_role", {}) or {})
    _patched_role_fees = {
        key: (100 if int(value or 0) == 150 else value)
        for key, value in _role_fees.items()
    }
    if _patched_role_fees != _role_fees:
        _changes["specify_fee_by_role"] = _patched_role_fees

    _game_role_fees = dict(getattr(_rule, "specify_fee_by_game_role", {}) or {})
    _patched_game_role_fees = {
        key: (100 if int(value or 0) == 150 else value)
        for key, value in _game_role_fees.items()
    }
    if _patched_game_role_fees != _game_role_fees:
        _changes["specify_fee_by_game_role"] = _patched_game_role_fees

    if _changes:
        _replace_rule(_rule_key, **_changes)


_order_rules.validate_rules()


# Discord's self-service catalog stores the quantity label separately from OrderRule.
# Patch NG entries to "小時" so the selector agrees with the new hourly pricing.
_HOURLY_NG_RULE_KEYS = {
    "valorant_entertain_ng",
    "valorant_ascendant_ng",
    "valorant_immortal_ng",
    "valorant_radiant_ng",
    "lol_entertain_ng",
    "lol_master_ng",
    "lol_grandmaster_ng",
    "lol_elite_ng",
}


def _patch_discord_catalog() -> None:
    try:
        from . import orders as _orders
    except ModuleNotFoundError as exc:
        # Web-only environments do not install discord.py and do not use this catalog.
        if exc.name == "discord":
            return
        raise

    for _groups in _orders.SELF_SERVICE_ORDER_CATALOG.values():
        for _group in _groups:
            for _detail in _group.get("details", []):
                if str(_detail.get("rule_key") or "") in _HOURLY_NG_RULE_KEYS:
                    _detail["quantity_unit"] = "小時"


if importlib.util.find_spec("discord") is not None:
    _patch_discord_catalog()


# Avoid leaking helper names as part of the services package API.
del _rule_key, _changes
