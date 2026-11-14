from __future__ import annotations

import json

from services.order_rules import (
    AW_COLLISION_ORDER_RULE_KEYS,
    AW_COLLISION_RECEIVER_ROLE_ID,
    COIN_WASH_ORDER_RULE_KEYS,
    HALFCOIN_RECEIVER_ROLE_ID,
    ORDER_RULES,
    get_allowed_role_ids,
    get_required_game_role_ids,
    get_required_role_ids,
    role_ids_match_requirements,
)
from shared.order_acceptance import _effective_claim_role_requirements
from web.app.services.role_catalog import COMPANION_ROLE_IDS


def cached_staff_role_ids(member) -> set[str]:
    """Only use the synced Discord role IDs; display/legacy staff flags are not authority."""
    raw = getattr(member, "roles_json", None)
    if isinstance(raw, (list, tuple, set)):
        parsed = raw
    else:
        try:
            parsed = json.loads(str(raw or "[]"))
        except (TypeError, ValueError):
            return set()
    if not isinstance(parsed, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in parsed if str(item).strip()}


def dispatch_assignment_role_requirements(order) -> tuple[set[str], set[str], set[str]]:
    rule_key = str(getattr(order, "order_rule_key", None) or "").strip()
    acceptance_meta = getattr(order, "dispatch_acceptance_meta", None)
    if not rule_key and isinstance(acceptance_meta, dict):
        rule_key = str(acceptance_meta.get("order_rule_key") or "").strip()

    # Override historical claim snapshots: only the corresponding receiver
    # group may be shown in CS's Web dispatch assignment picker.
    if rule_key in AW_COLLISION_ORDER_RULE_KEYS:
        return {AW_COLLISION_RECEIVER_ROLE_ID}, set(), set()
    if rule_key in COIN_WASH_ORDER_RULE_KEYS:
        return {HALFCOIN_RECEIVER_ROLE_ID}, set(), set()

    if isinstance(acceptance_meta, dict):
        allowed = _as_role_id_set(acceptance_meta.get("allowed_role_ids_json"))
        required_game = _as_role_id_set(acceptance_meta.get("required_game_role_ids_json"))
        allowed, required_game = _effective_claim_role_requirements(
            rule_key, allowed, required_game
        )
        rule = ORDER_RULES.get(rule_key)
        extras = set(get_required_role_ids(rule)) if rule is not None else set()
        return allowed, required_game, extras

    rule = ORDER_RULES.get(rule_key)
    if rule is not None:
        return (
            set(get_allowed_role_ids(rule)),
            set(get_required_game_role_ids(rule)),
            set(get_required_role_ids(rule)),
        )

    # Legacy manually created orders retain the previous companion-only picker.
    return set(COMPANION_ROLE_IDS), set(), set()


def _as_role_id_set(raw) -> set[str]:
    if isinstance(raw, (list, tuple, set)):
        return {str(x).strip() for x in raw if str(x).strip()}
    try:
        parsed = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return set()
    return _as_role_id_set(parsed) if isinstance(parsed, list) else set()


def is_eligible_dispatch_assignee(order, member) -> bool:
    if member is None or not bool(getattr(member, "is_active", False)):
        return False

    staff_roles = cached_staff_role_ids(member)
    if not staff_roles:
        return False

    allowed, required_game, required_extra = dispatch_assignment_role_requirements(order)
    return (
        bool(allowed)
        and role_ids_match_requirements(staff_roles, allowed, required_game)
        and required_extra.issubset(staff_roles)
    )


def eligible_dispatch_assignees(order, candidates: list) -> list:
    return [member for member in candidates if is_eligible_dispatch_assignee(order, member)]


__all__ = [
    "cached_staff_role_ids",
    "dispatch_assignment_role_requirements",
    "is_eligible_dispatch_assignee",
    "eligible_dispatch_assignees",
]
