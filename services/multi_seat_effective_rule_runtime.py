from __future__ import annotations

from dataclasses import replace


_INSTALLED = False

# These six rules existed before companion count became an independent field.
# Old manager overrides may therefore still contain the historical fixed-1 staff
# fields. Keep every business override (price, label, roles, benefit switches, etc.)
# but normalize only the structural fields that the migration made obsolete.
_DELTA_SHARED_COUNT_KEYS = {
    "basic_entertain_single",
    "basic_entertain_female_single",
    "basic_entertain_male_single",
    "basic_mobile_entertain_single",
    "basic_mobile_entertain_female_single",
    "basic_mobile_entertain_male_single",
}


def _normalize_delta_shared_count_rule(key: str, rule):
    if str(key) not in _DELTA_SHARED_COUNT_KEYS:
        return rule

    normalized = replace(
        rule,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=2,
        price_multiply_player_count=False,
        max_specified_count=2,
    )

    from services.order_rules import validate_rule_definition

    validate_rule_definition(str(key), normalized)
    return normalized


def install_multi_seat_effective_rule_runtime() -> None:
    """Normalize stale pre-migration override structure on every effective read.

    EffectiveOrderRules deliberately reapplies manager overrides after code rules.
    That is correct for ordinary business fields, but old overrides can carry the
    pre-migration fixed single-seat structure. Wrapping the instance resolver keeps
    those overrides intact while guaranteeing the new shared-count invariant.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services.order_rules import ORDER_RULES

    if getattr(ORDER_RULES, "_multi_seat_effective_rule_runtime_installed", False):
        _INSTALLED = True
        return

    original_effective = ORDER_RULES._effective

    def _effective(key: str):
        rule = original_effective(str(key))
        return _normalize_delta_shared_count_rule(str(key), rule)

    ORDER_RULES._effective = _effective
    ORDER_RULES._multi_seat_effective_rule_runtime_installed = True
    _INSTALLED = True


__all__ = ["install_multi_seat_effective_rule_runtime"]
