from __future__ import annotations


def get_manager_point_benefit_setting(rule_key: str) -> bool | None:
    """Return an explicit manager-published point-benefit setting, if present."""

    key = str(rule_key or "").strip()
    if not key:
        return None

    try:
        from services.order_rule_store import (
            get_active_override,
            get_custom_rule_definition,
        )

        active_payload = (get_active_override(key) or {}).get("payload") or {}
        if isinstance(active_payload, dict) and "point_benefits_allowed" in active_payload:
            return bool(active_payload.get("point_benefits_allowed"))

        custom_payload = (get_custom_rule_definition(key) or {}).get("payload") or {}
        if isinstance(custom_payload, dict) and "point_benefits_allowed" in custom_payload:
            return bool(custom_payload.get("point_benefits_allowed"))
    except Exception:
        return None

    return None
