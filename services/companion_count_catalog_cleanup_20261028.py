from __future__ import annotations

from dataclasses import replace
from typing import Any


_INSTALLED = False


# Stable selector values are intentional. Already-rendered Discord messages store
# these values, so the wording can change to 「機密」 while `secret_single` remains a
# valid selection and resolves to the new count-enabled canonical rule.
_DELTA_TECH_CANONICAL = (
    ("delta_desktop_basic", "basic_tech_secret_single", "機密", "secret_single", {1: 400, 2: 750}),
    ("delta_desktop_basic", "basic_tech_topsecret_single", "絕密", "topsecret_single", {1: 450, 2: 850}),
    ("delta_mobile_basic", "basic_mobile_tech_secret_single", "機密", "mobile_secret_single", {1: 380, 2: 760}),
    ("delta_mobile_basic", "basic_mobile_tech_topsecret_single", "絕密", "mobile_topsecret_single", {1: 420, 2: 840}),
)

_DELTA_ENTERTAIN_CANONICAL = (
    ("basic_entertain_single", {1: 320, 2: 600}),
    ("basic_entertain_female_single", {1: 320, 2: 600}),
    ("basic_entertain_male_single", {1: 320, 2: 600}),
    ("basic_mobile_entertain_single", {1: 320, 2: 600}),
    ("basic_mobile_entertain_female_single", {1: 320, 2: 600}),
    ("basic_mobile_entertain_male_single", {1: 320, 2: 600}),
)

_SWEET_PREFIX_CATEGORIES = (
    ("delta_desktop", "delta_desktop_basic"),
    ("delta_mobile", "delta_mobile_basic"),
    ("steam", "steam"),
    ("valorant", "valorant"),
    ("lol", "lol"),
    ("apex", "apex"),
)

_SWEET_GAME_LABELS = {
    "delta_desktop": "三角洲端遊",
    "delta_mobile": "三角洲手遊",
    "steam": "Steam",
    "valorant": "特戰英豪",
    "lol": "英雄聯盟",
    "apex": "APEX",
}


def _set_code_rule(order_rules, key: str, rule) -> None:
    """Replace the real base rule and its immutable fallback together."""
    dict.__setitem__(order_rules.ORDER_RULES, str(key), rule)
    order_rules._BASE_ORDER_RULES[str(key)] = rule


def _as_selectable_count_rule(rule, *, maximum: int):
    # Keep the existing internal label for Web/history compatibility. Customer-facing
    # Discord wording comes from the shared catalog rows below, not from rule.label.
    return replace(
        rule,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=int(maximum),
        price_multiply_player_count=False,
        max_specified_count=int(maximum),
        catalog_group_label="",
    )


def _install_delta_tech_count_rules(order_rules, multi_seat) -> None:
    for _category, key, _label, _value, prices in _DELTA_TECH_CANONICAL:
        # Read the code/base value directly so a stale DB override cannot become the
        # source for this structural migration.
        rule = order_rules.get_base_rule(key)
        migrated = _as_selectable_count_rule(rule, maximum=2)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _install_delta_entertain_count_rules(order_rules, multi_seat) -> None:
    for key, prices in _DELTA_ENTERTAIN_CANONICAL:
        rule = order_rules.get_base_rule(key)
        migrated = _as_selectable_count_rule(rule, maximum=2)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _sweet_canonical_key(prefix: str, mode: str) -> str:
    return f"{prefix}_sweet_{mode}"


def _install_sweet_canonical_rules(order_rules, multi_seat) -> None:
    """Add count-neutral public Sweet rules; keep historical fixed-seat keys intact."""
    for prefix, _category in _SWEET_PREFIX_CATEGORIES:
        specs = (
            ("female", f"{prefix}_sweet_female_single", "女陪"),
            ("male", f"{prefix}_sweet_male_single", "男陪"),
            ("any", f"{prefix}_sweet_double_any", "不限"),
        )
        for mode, template_key, semantic_label in specs:
            key = _sweet_canonical_key(prefix, mode)
            if dict.__contains__(order_rules.ORDER_RULES, key):
                rule = dict.__getitem__(order_rules.ORDER_RULES, key)
            else:
                template = order_rules.get_base_rule(template_key)
                rule = replace(
                    template,
                    key=key,
                    label=f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜{semantic_label}",
                    price=520,
                    catalog_group_label="",
                )

            rule = _as_selectable_count_rule(rule, maximum=2)
            order_rules.validate_rule_definition(key, rule)
            _set_code_rule(order_rules, key, rule)
            multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = {1: 520, 2: 1314}


def _replace_catalog_group(
    orders,
    category: str,
    group_label: str,
    rows: list[dict[str, Any]],
) -> None:
    groups = orders.SELF_SERVICE_ORDER_CATALOG.get(str(category), [])
    for group in groups:
        if str(group.get("label") or "") == str(group_label):
            group["details"] = [dict(item) for item in rows]
            return
    groups.append({"label": str(group_label), "details": [dict(item) for item in rows]})


def _install_direct_catalog_rows(orders) -> None:
    # Delta technical third field is now rank/type only. Stable historical values
    # remain so an already-rendered quick-order ticket continues working after deploy.
    for category in ("delta_desktop_basic", "delta_mobile_basic"):
        rows = [
            {
                "label": label,
                "value": value,
                "rule_key": key,
                "quantity_unit": "小時",
                "min_quantity": 1,
                "max_quantity": 24,
            }
            for row_category, key, label, value, _prices in _DELTA_TECH_CANONICAL
            if row_category == category
        ]
        _replace_catalog_group(orders, category, "技術陪", rows)

    # Sweet third field is gender/type only; headcount is the independent control.
    for prefix, category in _SWEET_PREFIX_CATEGORIES:
        _replace_catalog_group(
            orders,
            category,
            "甜蜜單",
            [
                {
                    "label": "女陪",
                    "value": "female_single",
                    "rule_key": _sweet_canonical_key(prefix, "female"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "男陪",
                    "value": "male_single",
                    "rule_key": _sweet_canonical_key(prefix, "male"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "不限",
                    "value": "any",
                    "rule_key": _sweet_canonical_key(prefix, "any"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
            ],
        )


def _persist_structural_override_migration(order_rules) -> None:
    """Publish one canonical version for any stale stored built-in override."""
    try:
        from services.order_rule_store import (
            load_active_overrides,
            normalize_builtin_rule_override_payload,
            publish_rule_override,
        )
    except Exception:
        return

    active = load_active_overrides()
    changed = False
    for key, item in active.items():
        original_payload = dict(item.get("payload") or {})
        payload = normalize_builtin_rule_override_payload(key, original_payload)
        if payload == original_payload:
            continue
        try:
            publish_rule_override(
                rule_key=key,
                payload=payload,
                actor_discord_id="system",
                actor_display_name="2026-10-28 companion-count migration",
                expected_active_version=int(item.get("version") or 0),
                action="system_migrate_companion_count_20261028",
            )
            changed = True
        except Exception as exc:
            print(f"[companion-count] override migration skipped {key}: {exc}", flush=True)

    if changed:
        order_rules.invalidate_rule_override_cache()


def _refresh_derived_maps(orders, order_rules) -> None:
    for key, rule in order_rules.ORDER_RULES.items():
        label = str(getattr(rule, "label", "") or "")
        if not label:
            continue
        orders.ORDER_RULE_KEY_BY_LABEL[label] = str(key)
        orders.ORDER_ITEM_TO_CATEGORY[label] = str(rule.category)
        items = orders.ORDER_ITEMS_BY_CATEGORY.setdefault(str(rule.category), [])
        if label not in items:
            items.append(label)
        if bool(getattr(rule, "allow_specify", False)):
            orders.SPECIAL_COMPANION_ITEMS.add(label)
        maximum = getattr(rule, "max_quantity", None)
        if maximum is None or int(maximum or 1) > 1:
            orders.QUANTITY_SELECT_ITEMS.add(label)


def install_companion_count_catalog_cleanup_20261028() -> None:
    """Install latest count-neutral rules/catalog without read-time rule overlays."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import multi_seat_order_policy_20261028 as multi_seat
    from services import order_rules, orders

    _install_delta_tech_count_rules(order_rules, multi_seat)
    _install_delta_entertain_count_rules(order_rules, multi_seat)
    _install_sweet_canonical_rules(order_rules, multi_seat)
    _install_direct_catalog_rows(orders)
    _persist_structural_override_migration(order_rules)
    _refresh_derived_maps(orders, order_rules)
    _INSTALLED = True


# Compatibility import only. No Discord-only catalog monkey patch remains.
def install_companion_count_discord_runtime_20261028() -> None:
    return None


__all__ = [
    "install_companion_count_catalog_cleanup_20261028",
    "install_companion_count_discord_runtime_20261028",
]
