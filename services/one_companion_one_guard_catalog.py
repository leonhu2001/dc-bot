from __future__ import annotations

from services.order_rules import (
    ALL_RECEIVER_ROLES,
    DELTA_DESKTOP_GAME_ROLE,
    DELTA_MOBILE_GAME_ROLE,
    ORDER_RULES,
    OrderRule,
    validate_rule_definition,
)


GROUP_LABEL = "一陪一護"
MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS = frozenset({
    "basic_mobile_one_companion_one_guard_secret",
    "basic_mobile_one_companion_one_guard_topsecret",
})

_RULE_SPECS = (
    (
        "delta_desktop_basic",
        "basic_one_companion_one_guard_secret",
        "一陪一護〈端遊〉｜機密",
        720,
        DELTA_DESKTOP_GAME_ROLE,
        "secret",
        "機密",
    ),
    (
        "delta_desktop_basic",
        "basic_one_companion_one_guard_topsecret",
        "一陪一護〈端遊〉｜絕密",
        770,
        DELTA_DESKTOP_GAME_ROLE,
        "topsecret",
        "絕密",
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_one_companion_one_guard_secret",
        "一陪一護〈手遊〉｜機密",
        700,
        DELTA_MOBILE_GAME_ROLE,
        "mobile_secret",
        "機密",
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_one_companion_one_guard_topsecret",
        "一陪一護〈手遊〉｜絕密",
        740,
        DELTA_MOBILE_GAME_ROLE,
        "mobile_topsecret",
        "絕密",
    ),
)


def _install_rules() -> None:
    # Keep both desktop and mobile rule definitions resolvable for historical
    # orders/snapshots. Mobile visibility is controlled by the handheld catalog
    # policy rather than by deleting canonical resolver data.
    for category, key, _legacy_label, price, game_roles, _value, detail_label in _RULE_SPECS:
        if key in ORDER_RULES:
            continue

        rule = OrderRule(
            category=category,
            key=key,
            label=str(detail_label),
            pricing_type="hourly",
            price=price,
            unit_label="H",
            allowed_roles=ALL_RECEIVER_ROLES,
            required_staff_count=2,
            min_quantity=1,
            max_quantity=24,
            allow_specify=False,
            min_protector_count=1,
            required_game_roles=game_roles,
            catalog_group_label=GROUP_LABEL,
        )
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule


def _catalog_details(category: str) -> list[dict]:
    return [
        {
            "label": detail_label,
            "value": value,
            "rule_key": key,
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        }
        for (
            rule_category,
            key,
            _label,
            _price,
            _game_roles,
            value,
            detail_label,
        ) in _RULE_SPECS
        if rule_category == category
    ]


def _install_catalog_group(category: str) -> None:
    from services import orders

    groups = orders.SELF_SERVICE_ORDER_CATALOG.setdefault(category, [])
    details = _catalog_details(category)
    if not details:
        return

    existing = next(
        (group for group in groups if str(group.get("label") or "") == GROUP_LABEL),
        None,
    )
    if existing is None:
        groups.append({"label": GROUP_LABEL, "details": details})
        return

    existing_details = existing.setdefault("details", [])
    existing_keys = {
        str(item.get("rule_key") or "")
        for item in existing_details
    }
    for detail in details:
        if detail["rule_key"] not in existing_keys:
            existing_details.append(detail)


def install_one_companion_one_guard_catalog() -> None:
    """Install Delta Force one-companion/one-guard rules and resolver data.

    The mobile group remains in the resolver catalog only for historical/stale
    interactions. services.delta_mobile_result_catalog_20261101 filters it out of
    the new mobile group selector. Desktop visibility remains unchanged.
    """
    _install_rules()
    _install_catalog_group("delta_desktop_basic")
    _install_catalog_group("delta_mobile_basic")


__all__ = [
    "GROUP_LABEL",
    "MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS",
    "install_one_companion_one_guard_catalog",
]
