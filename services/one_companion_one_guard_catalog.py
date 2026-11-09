from __future__ import annotations

from services.order_rules import (
    ALL_RECEIVER_ROLES,
    DELTA_DESKTOP_GAME_ROLE,
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
        800,
        DELTA_DESKTOP_GAME_ROLE,
        "secret",
        "機密",
    ),
    (
        "delta_desktop_basic",
        "basic_one_companion_one_guard_topsecret",
        "一陪一護〈端遊〉｜絕密",
        850,
        DELTA_DESKTOP_GAME_ROLE,
        "topsecret",
        "絕密",
    ),
)


def _retire_mobile_variant() -> None:
    """Remove the discontinued handheld variant from active runtime registries."""
    from services import order_rules, orders

    for key in MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS:
        if dict.__contains__(order_rules.ORDER_RULES, key):
            dict.__delitem__(order_rules.ORDER_RULES, key)
        order_rules._BASE_ORDER_RULES.pop(key, None)
        order_rules.ORDER_RULES._custom_cache.pop(key, None)
        order_rules.ORDER_RULES._override_cache.pop(key, None)

    mobile_groups = orders.SELF_SERVICE_ORDER_CATALOG.setdefault("delta_mobile_basic", [])
    mobile_groups[:] = [
        group
        for group in mobile_groups
        if str(group.get("label") or "") != GROUP_LABEL
        and not any(
            str(detail.get("rule_key") or "") in MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS
            for detail in group.get("details", [])
        )
    ]

    for label, rule_key in tuple(orders.ORDER_RULE_KEY_BY_LABEL.items()):
        if str(rule_key or "") in MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS:
            orders.ORDER_RULE_KEY_BY_LABEL.pop(label, None)
            orders.ORDER_ITEM_TO_CATEGORY.pop(label, None)


def _install_rules() -> None:
    for category, key, _legacy_label, price, game_roles, value, detail_label in _RULE_SPECS:
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
            allow_specify=True,
            max_specified_count=2,
            specify_fee_default=100,
            specify_fee_by_role={role: 100 for role in ALL_RECEIVER_ROLES},
            specify_free_min_units=2,
            specify_free_basis="quantity",
            min_protector_count=1,
            required_game_roles=game_roles,
            catalog_group_label=GROUP_LABEL,
            note=(
                "一小時內 8 殺；指定打手每人 +100T，2H 以上免指定費。"
                if value == "secret"
                else "一小時內 7 殺；指定打手每人 +100T，2H 以上免指定費。"
            ),
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
    """Install the desktop Delta one-companion/one-guard product only.

    The handheld variant is retired from active products and rules. Historical
    order records remain untouched in storage.
    """
    _retire_mobile_variant()
    _install_rules()
    _install_catalog_group("delta_desktop_basic")


__all__ = [
    "GROUP_LABEL",
    "MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS",
    "install_one_companion_one_guard_catalog",
]
