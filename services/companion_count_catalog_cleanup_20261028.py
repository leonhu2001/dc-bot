from __future__ import annotations

from dataclasses import replace


_INSTALLED = False


_DELTA_TECH_CANONICAL = (
    (
        "delta_desktop_basic",
        "basic_tech_secret_single",
        "機密",
        "secret_single",
        {1: 400, 2: 750},
    ),
    (
        "delta_desktop_basic",
        "basic_tech_topsecret_single",
        "絕密",
        "topsecret_single",
        {1: 450, 2: 850},
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_secret_single",
        "機密",
        "mobile_secret_single",
        {1: 380, 2: 760},
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_topsecret_single",
        "絕密",
        "mobile_topsecret_single",
        {1: 420, 2: 840},
    ),
)

_SWEET_PREFIX_CATEGORIES = (
    ("delta_desktop", "delta_desktop_basic"),
    ("delta_mobile", "delta_mobile_basic"),
    ("steam", "steam"),
    ("valorant", "valorant"),
    ("lol", "lol"),
    ("apex", "apex"),
)


def _set_code_rule(order_rules, key: str, rule) -> None:
    # ORDER_RULES is an EffectiveOrderRules dict subclass. Update both its code-rule
    # backing entry and get_base_rule's immutable-fallback map so every read path sees
    # the same structural migration while historical keys remain present.
    dict.__setitem__(order_rules.ORDER_RULES, str(key), rule)
    order_rules._BASE_ORDER_RULES[str(key)] = rule


def _as_selectable_count_rule(rule, *, maximum: int = 2):
    return replace(
        rule,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=int(maximum),
        price_multiply_player_count=False,
        max_specified_count=int(maximum),
    )


def _install_delta_tech_count_rules(order_rules, multi_seat) -> None:
    for _category, key, _label, _value, prices in _DELTA_TECH_CANONICAL:
        rule = order_rules.ORDER_RULES.get(key)
        if rule is None:
            raise RuntimeError(f"missing Delta technical rule: {key}")
        migrated = _as_selectable_count_rule(rule, maximum=2)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _install_sweet_count_rules(order_rules, multi_seat) -> None:
    for prefix, _category in _SWEET_PREFIX_CATEGORIES:
        for suffix in ("female_single", "male_single", "double_any"):
            key = f"{prefix}_sweet_{suffix}"
            rule = order_rules.ORDER_RULES.get(key)
            if rule is None:
                raise RuntimeError(f"missing sweet companion rule: {key}")
            migrated = _as_selectable_count_rule(rule, maximum=2)
            order_rules.validate_rule_definition(key, migrated)
            _set_code_rule(order_rules, key, migrated)
            multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = {1: 520, 2: 1314}


def _replace_delta_tech_catalog(orders) -> None:
    by_category: dict[str, list[dict]] = {}
    for category, key, label, value, _prices in _DELTA_TECH_CANONICAL:
        by_category.setdefault(category, []).append({
            "label": label,
            "value": value,
            "rule_key": key,
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        })

    for category, details in by_category.items():
        groups = orders.SELF_SERVICE_ORDER_CATALOG.get(category, [])
        target_keys = {str(item["rule_key"]) for item in details}
        for group in groups:
            current_keys = {
                str(item.get("rule_key") or "")
                for item in group.get("details", [])
            }
            if not (current_keys & target_keys):
                continue
            group["details"] = [dict(item) for item in details]
            break


def _replace_sweet_catalog(orders) -> None:
    for prefix, category in _SWEET_PREFIX_CATEGORIES:
        groups = orders.SELF_SERVICE_ORDER_CATALOG.get(category, [])
        for group in groups:
            if str(group.get("label") or "") != "甜蜜單":
                continue
            group["details"] = [
                {
                    "label": "女陪",
                    "value": "female_single",
                    "rule_key": f"{prefix}_sweet_female_single",
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "男陪",
                    "value": "male_single",
                    "rule_key": f"{prefix}_sweet_male_single",
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "不限",
                    "value": "double_any",
                    "rule_key": f"{prefix}_sweet_double_any",
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
            ]
            break


def _install_effective_rule_normalizer(order_rules) -> None:
    rules = order_rules.ORDER_RULES
    if getattr(rules, "_companion_count_catalog_cleanup_installed", False):
        return

    structural_keys = {
        key
        for _category, key, _label, _value, _prices in _DELTA_TECH_CANONICAL
    }
    structural_keys.update(
        f"{prefix}_sweet_{suffix}"
        for prefix, _category in _SWEET_PREFIX_CATEGORIES
        for suffix in ("female_single", "male_single", "double_any")
    )

    original_effective = rules._effective

    def _effective(key: str):
        text_key = str(key)
        rule = original_effective(text_key)
        if text_key not in structural_keys:
            return rule
        normalized = _as_selectable_count_rule(rule, maximum=2)
        order_rules.validate_rule_definition(text_key, normalized)
        return normalized

    rules._effective = _effective
    rules._companion_count_catalog_cleanup_installed = True


def install_companion_count_catalog_cleanup_20261028() -> None:
    """Keep spec selectors semantic while companion count lives in its own control.

    Old single/double rule keys are intentionally retained for order snapshots and
    saved selections. New checkout uses one canonical rule per semantic choice and
    the shared companion-count selector for 1/2 seats.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import multi_seat_order_policy_20261028 as multi_seat
    from services import order_rules
    from services import orders

    _install_delta_tech_count_rules(order_rules, multi_seat)
    _install_sweet_count_rules(order_rules, multi_seat)
    _replace_delta_tech_catalog(orders)
    _replace_sweet_catalog(orders)
    _install_effective_rule_normalizer(order_rules)
    _INSTALLED = True


__all__ = ["install_companion_count_catalog_cleanup_20261028"]
