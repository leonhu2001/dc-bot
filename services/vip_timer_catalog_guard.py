from __future__ import annotations

from typing import Any


_INSTALLED = False


def public_timer_rule_keys() -> set[str]:
    """Return rule keys actually selectable in the current Discord catalog."""
    from services.order_product_status import is_order_product_active
    from services.order_rules import ORDER_RULES
    from services.orders import (
        CATALOG_HIDDEN_RULE_KEYS,
        SELF_SERVICE_ORDER_CATALOG,
    )

    result: set[str] = set()

    for groups in SELF_SERVICE_ORDER_CATALOG.values():
        for group in groups or []:
            for detail in group.get("details", []) or []:
                key = str(detail.get("rule_key") or "").strip()
                if not key or key in CATALOG_HIDDEN_RULE_KEYS:
                    continue
                rule = ORDER_RULES.get(key)
                if rule is None:
                    continue
                if str(getattr(rule, "pricing_type", "") or "") != "hourly":
                    continue
                if int(getattr(rule, "price", 0) or 0) <= 0:
                    continue
                if int(getattr(rule, "min_quantity", 1) or 1) > 1:
                    continue
                if not is_order_product_active(key):
                    continue
                result.add(key)

    # Manager-created products may not exist in the static catalog mapping.
    is_custom = getattr(ORDER_RULES, "is_custom", None)
    if callable(is_custom):
        for key, rule in ORDER_RULES.items():
            key = str(key or "").strip()
            if not key:
                continue
            try:
                if not bool(is_custom(key)):
                    continue
            except Exception:
                continue
            if str(getattr(rule, "pricing_type", "") or "") != "hourly":
                continue
            if int(getattr(rule, "price", 0) or 0) <= 0:
                continue
            if int(getattr(rule, "min_quantity", 1) or 1) > 1:
                continue
            if not is_order_product_active(key):
                continue
            result.add(key)

    return result


def is_public_timer_rule(rule_key: Any) -> bool:
    key = str(rule_key or "").strip()
    return bool(key) and key in public_timer_rule_keys()


def install_vip_timer_catalog_guard() -> None:
    """Filter timer source/switch options to current public hourly products."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer as timer

    original_public_hourly_rules = timer.public_hourly_rules
    original_rule_snapshot = timer.rule_snapshot

    def guarded_public_hourly_rules():
        allowed = public_timer_rule_keys()
        return [
            dict(row)
            for row in original_public_hourly_rules()
            if str(row.get("rule_key") or "").strip() in allowed
        ]

    def guarded_rule_snapshot(rule_key: str):
        key = timer.strip_vip_timer_rule_key(rule_key)
        if not is_public_timer_rule(key):
            raise ValueError(
                "這個玩法目前不能用於 VIP 自由計時，請改選其他玩法。"
            )
        return original_rule_snapshot(key)

    timer.public_hourly_rules = guarded_public_hourly_rules
    timer.rule_snapshot = guarded_rule_snapshot

    _INSTALLED = True


__all__ = [
    "install_vip_timer_catalog_guard",
    "is_public_timer_rule",
    "public_timer_rule_keys",
]
