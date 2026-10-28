from __future__ import annotations

from dataclasses import replace
import sys


SWEET_COMPANION_ROLE_KEY = "sweet_companion"
SWEET_COMPANION_ROLE_ID = "1564966706407940248"
SWEET_COMPANION_ROLE_LABEL = "甜蜜陪"

_INSTALLED = False


def is_sweet_rule_key(rule_key: str) -> bool:
    """Return whether this is a new public count-neutral Sweet rule."""
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


def _persist_sweet_override_migration(order_rules) -> None:
    """Write the Sweet qualification into saved manager overrides once.

    This replaces the old strategy of wrapping EffectiveOrderRules._effective on
    every read. Existing manager price/role/benefit settings stay intact; only the
    new mandatory Sweet qualification is added to the stored rule payload.
    """
    try:
        from services.order_rule_store import load_active_overrides, publish_rule_override
    except Exception:
        return

    active = load_active_overrides()
    changed = False
    for key, item in active.items():
        if not is_sweet_rule_key(key):
            continue

        original_payload = dict(item.get("payload") or {})
        payload = dict(original_payload)
        required = [
            str(value)
            for value in (payload.get("required_game_roles") or [])
            if str(value).strip()
        ]
        if SWEET_COMPANION_ROLE_KEY not in required:
            required.append(SWEET_COMPANION_ROLE_KEY)
        payload["required_game_roles"] = required
        payload["catalog_group_label"] = ""

        if payload == original_payload:
            continue

        try:
            publish_rule_override(
                rule_key=key,
                payload=payload,
                actor_discord_id="system",
                actor_display_name="2026-10-28 sweet qualification migration",
                expected_active_version=int(item.get("version") or 0),
                action="system_migrate_sweet_qualification_20261028",
            )
            changed = True
        except Exception as exc:
            print(
                f"[sweet-companion] override migration skipped {key}: {exc}",
                flush=True,
            )

    if changed:
        order_rules.invalidate_rule_override_cache()


def _install_direct_sweet_rules(order_rules) -> None:
    rules = order_rules.ORDER_RULES
    for key in list(dict.keys(rules)):
        text_key = str(key)
        if not is_sweet_rule_key(text_key):
            continue
        base = dict.__getitem__(rules, text_key)
        guarded = _enforce_sweet_requirement(text_key, base)
        order_rules.validate_rule_definition(text_key, guarded)
        dict.__setitem__(rules, text_key, guarded)
        order_rules._BASE_ORDER_RULES[text_key] = guarded

    _persist_sweet_override_migration(order_rules)


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
        # 甜蜜陪 is an additional qualification and therefore must be held together
        # with the normal game/service qualification.
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

    # Some modules can already hold a direct import of the matcher. Keep those
    # references synchronized with the one canonical matcher implementation.
    for module_name in ("views.smart_dispatch", "shared.order_acceptance"):
        module = sys.modules.get(module_name)
        if module is not None:
            setattr(module, "role_ids_match_requirements", role_ids_match_requirements)


def install_sweet_companion_policy_20261028() -> None:
    """Require 甜蜜陪 in addition to every new count-neutral Sweet qualification."""
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

    _install_direct_sweet_rules(order_rules)
    _install_and_matcher(order_rules)
    _INSTALLED = True


__all__ = [
    "SWEET_COMPANION_ROLE_ID",
    "SWEET_COMPANION_ROLE_KEY",
    "SWEET_COMPANION_ROLE_LABEL",
    "is_sweet_rule_key",
    "install_sweet_companion_policy_20261028",
]
