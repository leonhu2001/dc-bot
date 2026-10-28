from __future__ import annotations


def install_entertainment_companion_selector_compat_20261028() -> None:
    """Keep old selector values while only changing the customer-facing labels.

    Existing saved/self-service state may still contain the original values
    (single/double and mobile_single/mobile_double). The new unrestricted-gender
    choices must continue resolving those values instead of forcing a migration.
    """

    from services import orders

    legacy_values = {
        "basic_entertain_single": "single",
        "basic_entertain_double": "double",
        "basic_mobile_entertain_single": "mobile_single",
        "basic_mobile_entertain_double": "mobile_double",
    }

    for groups in orders.SELF_SERVICE_ORDER_CATALOG.values():
        for group in groups:
            for detail in group.get("details", []):
                rule_key = str(detail.get("rule_key") or "")
                if rule_key in legacy_values:
                    detail["value"] = legacy_values[rule_key]


__all__ = ["install_entertainment_companion_selector_compat_20261028"]
