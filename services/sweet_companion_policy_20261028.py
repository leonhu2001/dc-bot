from __future__ import annotations

from dataclasses import replace
import sys


SWEET_COMPANION_ROLE_KEY = "sweet_companion"
SWEET_COMPANION_ROLE_ID = "1564966706407940248"
SWEET_COMPANION_ROLE_LABEL = "甜蜜陪"

_INSTALLED = False


def is_sweet_rule_key(rule_key: str) -> bool:
    """Return whether this is a new public count-neutral Sweet rule.

    Legacy basic/game-specific single/double keys stay unchanged so historical
    orders and saved selections preserve their original rule snapshot semantics.
    New Discord Sweet checkout uses *_sweet_female / *_sweet_male / *_sweet_any.
    """
    key = str(rule_key or "")
    return key.endswith(("_sweet_female", "_sweet_male", "_sweet_any"))


def _enforce_sweet_requirement(rule_key: str, rule):
    if not is_sweet_rule_key(rule_key):
        return rule

    required = tuple(str(item) for item in (getattr(rule, "required_game_roles", ()) or ()))
    if SWEET_COMPANION_ROLE_KEY in required:
        return rule

    return replace(
        rule,
        required_game_roles=(*required, SWEET_COMPANION_ROLE_KEY),
    )


def _install_and_matcher(order_rules) -> None:
    if getattr(order_rules, "_sweet_companion_and_matcher_installed", False):
        return

    original_match = order_rules.role_ids_match_requirements

    def role_ids_match_requirements(
        member_role_ids,
        allowed_role_ids,
        required_game_role_ids=(),
    ) -> bool:
        member_roles = {
            str(role_id).strip()
            for role_id in (member_role_ids or [])
            if str(role_id).strip()
        }
        required_games = [
            str(role_id).strip()
            for role_id in (required_game_role_ids or [])
            if str(role_id).strip()
        ]

        # required_game_role_ids normally means "at least one of these game roles".
        # Sweet companion is different: it is an additional qualification and must
        # be held together with the normal service/game qualification.
        if SWEET_COMPANION_ROLE_ID in required_games:
            if SWEET_COMPANION_ROLE_ID not in member_roles:
                return False
            required_games = [
                role_id
                for role_id in required_games
                if role_id != SWEET_COMPANION_ROLE_ID
            ]

        return original_match(
            member_roles,
            allowed_role_ids,
            required_games,
        )

    order_rules.role_ids_match_requirements = role_ids_match_requirements
    order_rules._sweet_companion_and_matcher_installed = True

    # These modules normally import the matcher after services/__init__ finishes.
    # Patch already-loaded copies too, so test/reload order cannot weaken the gate.
    for module_name in ("views.smart_dispatch", "shared.order_acceptance"):
        module = sys.modules.get(module_name)
        if module is not None:
            setattr(module, "role_ids_match_requirements", role_ids_match_requirements)


def install_sweet_companion_policy_20261028() -> None:
    """Require 甜蜜陪 in addition to each new Sweet rule's normal qualification."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import order_rules

    # Register this system qualification only in the shared role lookup used by
    # rule snapshots/validation. It is intentionally not a public game/rank option.
    order_rules.GAME_ROLE_IDS_BY_KEY[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_ID
    order_rules.GAME_ROLE_LABELS_BY_KEY[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_LABEL
    order_rules.ALL_ROLE_IDS[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_ID
    order_rules.ALL_ROLE_LABELS[SWEET_COMPANION_ROLE_KEY] = SWEET_COMPANION_ROLE_LABEL

    rules = order_rules.ORDER_RULES

    # EffectiveOrderRules reapplies manager overrides on every read. Enforce this
    # structural qualification after that merge so an override cannot remove it.
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
            if not is_sweet_rule_key(str(rule_key)):
                continue
            rules[rule_key] = _enforce_sweet_requirement(str(rule_key), rules[rule_key])

    _install_and_matcher(order_rules)
    _INSTALLED = True


__all__ = [
    "SWEET_COMPANION_ROLE_ID",
    "SWEET_COMPANION_ROLE_KEY",
    "SWEET_COMPANION_ROLE_LABEL",
    "is_sweet_rule_key",
    "install_sweet_companion_policy_20261028",
]
