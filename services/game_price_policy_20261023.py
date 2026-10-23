from __future__ import annotations

from dataclasses import replace


# 2026-10-23 owner-approved public price lists. Keep the storefront/order-rule
# prices in one explicit policy so Discord display and checkout cannot drift.
GAME_PRICE_OVERRIDES: dict[str, int] = {
    # VALORANT
    "valorant_entertain_ng": 300,
    "valorant_entertain_ranked": 250,
    "valorant_ascendant_ng": 330,
    "valorant_ascendant_ranked": 290,
    "valorant_immortal_ng": 350,
    "valorant_immortal_ranked": 330,
    "valorant_radiant_ng": 380,
    "valorant_radiant_ranked": 370,
    # League of Legends
    "lol_entertain_aram": 300,
    "lol_entertain_ng": 300,
    "lol_entertain_ranked": 250,
    "lol_master_ng": 340,
    "lol_master_ranked": 300,
    "lol_grandmaster_ng": 360,
    "lol_grandmaster_ranked": 300,
    "lol_elite_ng": 400,
    "lol_elite_ranked": 400,
    # APEX Legends
    "apex_entertain_ng": 300,
    "apex_entertain_ranked": 350,
    "apex_diamond_ng": 400,
    "apex_diamond_ranked": 450,
    "apex_master_ng": 480,
    "apex_master_ranked": 530,
    "apex_predator_ng": 580,
    "apex_predator_ranked": 630,
    # STEAM
    "steam_play": 320,
}


_INSTALLED = False


def install_game_price_policy_20261023() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services.order_rules import ORDER_RULES

    missing: list[str] = []
    for rule_key, price in GAME_PRICE_OVERRIDES.items():
        rule = ORDER_RULES.get(rule_key)
        if rule is None:
            missing.append(rule_key)
            continue
        ORDER_RULES[rule_key] = replace(rule, price=int(price))

    if missing:
        raise RuntimeError(
            "2026-10-23 game price policy references missing order rules: "
            + ", ".join(sorted(missing))
        )

    _INSTALLED = True


__all__ = [
    "GAME_PRICE_OVERRIDES",
    "install_game_price_policy_20261023",
]
