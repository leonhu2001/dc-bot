from __future__ import annotations

from dataclasses import replace


SWEET_COMPANION_ROLE_KEY = "sweet_companion"
SWEET_COMPANION_ROLE_ID = "1564966706407940248"
SWEET_COMPANION_ROLE_LABEL = "甜蜜陪"
SWEET_RULE_PREFIX = "basic_sweet_"

_INSTALLED = False


def _enforce_sweet_requirement(rule_key: str, rule):
    if not str(rule_key).startswith(SWEET_RULE_PREFIX):
        return rule

    required = tuple(str(item) for item in (getattr(rule, "required_game_roles", ()) or ()))
    if SWEET_COMPANION_ROLE_KEY in required:
        return rule

    return replace(
        rule,
        required_game_roles=(*required, SWEET_COMPANION_ROLE_KEY),
    )


def install_sweet_companion_policy_20261028() -> None:
    """Make the sweet-companion role an additional AND gate for sweet orders.

    The existing required_game_roles acceptance/dispatch field is deliberately a
    generic second-stage AND qualification. Reusing it keeps Discord claims, Web
    claims, smart-dispatch candidate filtering, specified-staff validation and order
    snapshots on the same source of truth without turning 甜蜜陪 into a normal
    service-position role.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import order_rules

    # Register this system qualification only in the shared role lookup used by
    # rule snapshots/validation. It is not added to the public game/rank catalog.
    order_rules.GAME_ROLE_IDS_BY_KEY[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_ID
    order_rules.GAME_ROLE_LABELS_BY_KEY[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_LABEL
    order_rules.ALL_ROLE_IDS[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_ID
    order_rules.ALL_ROLE_LABELS[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_LABEL

    rules = order_rules.ORDER_RULES

    # EffectiveOrderRules reapplies manager overrides on every read. Enforce this
    # structural qualification after that merge so an old override cannot
    # accidentally remove the newly required sweet role.
    if hasattr(rules, "_effective"):
        if not getattr(rules, "_sweet_companion_policy_installed", False):
            original_effective = rules._effective

            def _effective(rule_key: str):
                rule = original_effective(str(rule_key))
                guarded = _enforce_sweet_requirement(str(rule_key), rule)
                order_rules.validate_rule_definition(str(rule_key), guarded)
                return guarded

            rules._effective = _effective
            rules._sweet_companion_policy_installed = True
    else:
        for rule_key in list(rules):
            if not str(rule_key).startswith(SWEET_RULE_PREFIX):
                continue
            rules[rule_key] = _enforce_sweet_requirement(str(rule_key), rules[rule_key])

    _INSTALLED = True


__all__ = [
    "SWEET_COMPANION_ROLE_ID",
    "SWEET_COMPANION_ROLE_KEY",
    "SWEET_COMPANION_ROLE_LABEL",
    "install_sweet_companion_policy_20261028",
]
