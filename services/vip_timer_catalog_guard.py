from __future__ import annotations

from typing import Any


_INSTALLED = False


def _allows_timer_minimum_override(key: str, rule) -> bool:
    """Teaching keeps its normal-order minimum but is still valid for VIP timing."""
    label = str(getattr(rule, "label", "") or "")
    key_text = str(key or "").lower()
    return "teaching" in key_text or "教學" in label


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
                if (
                    int(getattr(rule, "min_quantity", 1) or 1) > 1
                    and not _allows_timer_minimum_override(key, rule)
                ):
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
    """Filter customer-facing timer choices to current public hourly products.

    Keep ``vip_timer.rule_snapshot`` as the canonical low-level hourly-rule
    validator. Catalog eligibility belongs at the selection boundary, not inside
    the core snapshot function: patching the core function makes internal tools,
    migrations and unit tests depend on whichever UI catalog happens to be
    installed at runtime.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer as timer

    original_public_hourly_rules = timer.public_hourly_rules

    def guarded_public_hourly_rules():
        allowed = public_timer_rule_keys()
        return [
            dict(row)
            for row in original_public_hourly_rules()
            if str(row.get("rule_key") or "").strip() in allowed
        ]

    timer.public_hourly_rules = guarded_public_hourly_rules

    _INSTALLED = True


__all__ = [
    "install_vip_timer_catalog_guard",
    "is_public_timer_rule",
    "public_timer_rule_keys",
]
