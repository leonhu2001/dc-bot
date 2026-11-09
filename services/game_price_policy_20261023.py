from __future__ import annotations

from dataclasses import replace


# Latest owner-approved Nov 10 price images, preserving the earlier Valorant prices.
# Keep the storefront/order-rule
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
    "lol_entertain_aram": 350,
    "lol_entertain_ng": 350,
    "lol_entertain_ranked": 280,
    "lol_master_ng": 380,
    "lol_master_ranked": 300,
    "lol_grandmaster_ng": 390,
    "lol_grandmaster_ranked": 350,
    "lol_elite_ng": 400,
    "lol_elite_ranked": 450,
    # APEX Legends
    "apex_entertain_ng": 320,
    "apex_entertain_ranked": 350,
    "apex_diamond_ng": 380,
    "apex_diamond_ranked": 400,
    "apex_master_ng": 400,
    "apex_master_ranked": 450,
    "apex_predator_ng": 500,
    "apex_predator_ranked": 550,
    # Technical LoL ARAM remains selectable and follows the NG hourly rate.
    "lol_master_aram": 380,
    "lol_grandmaster_aram": 390,
    "lol_elite_aram": 400,
    # APEX ranked tier surcharges (platinum-or-below + 50 per rank step).
    **{
        f"{prefix}_ranked_tier_{rank}": base + 50 * steps
        for prefix, base in (
            ("apex_entertain", 350),
            ("apex_diamond", 400),
            ("apex_master", 450),
            ("apex_predator", 550),
        )
        for rank, steps in (("diamond", 1), ("master", 2), ("predator", 3))
    },
    # STEAM
    "steam_play": 350,
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
