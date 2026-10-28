from __future__ import annotations

from dataclasses import replace
from typing import Any


_INSTALLED = False


# IMPORTANT: selector values intentionally keep the historical *single* values.
# Existing Discord messages persist their option values inside the message payload.
# Changing secret_single -> secret broke those already-rendered components after a
# deploy. Customer-facing labels are count-neutral, but the stable value stays the
# old single value so old/new tickets resolve the same canonical rule.
_DELTA_TECH_CANONICAL = (
    (
        "delta_desktop_basic",
        "basic_tech_secret_single",
        "機密",
        "secret_single",
        {1: 400, 2: 750},
        "技術陪〈端遊〉｜機密",
    ),
    (
        "delta_desktop_basic",
        "basic_tech_topsecret_single",
        "絕密",
        "topsecret_single",
        {1: 450, 2: 850},
        "技術陪〈端遊〉｜絕密",
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_secret_single",
        "機密",
        "mobile_secret_single",
        {1: 380, 2: 760},
        "技術陪〈手遊〉｜機密",
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_topsecret_single",
        "絕密",
        "mobile_topsecret_single",
        {1: 420, 2: 840},
        "技術陪〈手遊〉｜絕密",
    ),
)

_DELTA_ENTERTAIN_CANONICAL = (
    (
        "basic_entertain_single",
        "娛樂陪〈端遊〉｜不限",
        {1: 320, 2: 600},
    ),
    (
        "basic_entertain_female_single",
        "娛樂陪〈端遊〉｜女陪",
        {1: 320, 2: 600},
    ),
    (
        "basic_entertain_male_single",
        "娛樂陪〈端遊〉｜男陪",
        {1: 320, 2: 600},
    ),
    (
        "basic_mobile_entertain_single",
        "娛樂陪〈手遊〉｜不限",
        {1: 320, 2: 600},
    ),
    (
        "basic_mobile_entertain_female_single",
        "娛樂陪〈手遊〉｜女陪",
        {1: 320, 2: 600},
    ),
    (
        "basic_mobile_entertain_male_single",
        "娛樂陪〈手遊〉｜男陪",
        {1: 320, 2: 600},
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

_SWEET_GAME_LABELS = {
    "delta_desktop": "三角洲端遊",
    "delta_mobile": "三角洲手遊",
    "steam": "Steam",
    "valorant": "特戰英豪",
    "lol": "英雄聯盟",
    "apex": "APEX",
}


def _set_code_rule(order_rules, key: str, rule) -> None:
    """Replace the actual code rule and immutable fallback together.

    This is deliberately not an EffectiveOrderRules read-time wrapper. Once the
    migration runs, the in-process base rule itself is the new rule.
    """
    dict.__setitem__(order_rules.ORDER_RULES, str(key), rule)
    order_rules._BASE_ORDER_RULES[str(key)] = rule


def _as_selectable_count_rule(rule, *, maximum: int, label: str | None = None):
    return replace(
        rule,
        label=str(label or rule.label),
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=int(maximum),
        price_multiply_player_count=False,
        max_specified_count=int(maximum),
        # Built-in catalog detail labels are authoritative. Leaving this blank also
        # prevents an old manager group override from turning 「機密」 back into
        # 「機密｜單陪」 inside the third selector.
        catalog_group_label="",
    )


def _install_delta_tech_count_rules(order_rules, multi_seat) -> None:
    # Historical *_double keys remain untouched for snapshots / completed orders.
    # New orders use the canonical single-key rule plus the independent count button.
    for _category, key, _label, _value, prices, rule_label in _DELTA_TECH_CANONICAL:
        rule = order_rules.ORDER_RULES.get(key)
        if rule is None:
            raise RuntimeError(f"missing Delta technical rule: {key}")
        migrated = _as_selectable_count_rule(rule, maximum=2, label=rule_label)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _install_delta_entertain_count_rules(order_rules, multi_seat) -> None:
    # The gender variants are created earlier by entertainment_companion_policy.
    # Normalize their actual base definitions here so a later read no longer needs
    # multi_seat_effective_rule_runtime to repair stale fixed-seat structure.
    for key, rule_label, prices in _DELTA_ENTERTAIN_CANONICAL:
        rule = order_rules.ORDER_RULES.get(key)
        if rule is None:
            raise RuntimeError(f"missing Delta entertainment rule: {key}")
        migrated = _as_selectable_count_rule(rule, maximum=2, label=rule_label)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _sweet_canonical_key(prefix: str, mode: str) -> str:
    return f"{prefix}_sweet_{mode}"


def _install_sweet_canonical_rules(order_rules, multi_seat) -> None:
    """Create count-neutral Sweet rules while retaining historical fixed-seat keys."""
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
                template = order_rules.ORDER_RULES.get(template_key)
                if template is None:
                    raise RuntimeError(f"missing sweet companion template: {template_key}")
                rule = replace(
                    template,
                    key=key,
                    label=f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜{semantic_label}",
                    price=520,
                    catalog_group_label="",
                )
            rule = _as_selectable_count_rule(
                rule,
                maximum=2,
                label=f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜{semantic_label}",
            )
            order_rules.validate_rule_definition(key, rule)
            _set_code_rule(order_rules, key, rule)
            multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = {1: 520, 2: 1314}


def _replace_catalog_group(orders, category: str, group_label: str, rows: list[dict[str, Any]]) -> None:
    groups = orders.SELF_SERVICE_ORDER_CATALOG.get(str(category), [])
    for group in groups:
        if str(group.get("label") or "") == str(group_label):
            group["details"] = [dict(item) for item in rows]
            return
    groups.append({"label": str(group_label), "details": [dict(item) for item in rows]})


def _install_direct_catalog_rows(orders) -> None:
    """Write the canonical catalog itself instead of patching Discord helper calls."""
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
            for row_category, key, label, value, _prices, _rule_label in _DELTA_TECH_CANONICAL
            if row_category == category
        ]
        _replace_catalog_group(orders, category, "技術陪", rows)

    for prefix, category in _SWEET_PREFIX_CATEGORIES:
        # female_single / male_single remain stable selector values. 「不限」 gets
        # its own count-neutral value so new tickets do not imply two seats merely
        # because the historical template key was *_double_any.
        rows = [
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
        ]
        _replace_catalog_group(orders, category, "甜蜜單", rows)


def _persist_structural_override_migration(order_rules) -> None:
    """Rewrite stale manager overrides in SQLite instead of masking them at read time."""
    try:
        from services.order_rule_store import load_active_overrides, publish_rule_override
    except Exception:
        return

    # Every key here now has an independent customer-facing companion-count control.
    # These invariants are structural; manager price/roles/benefit switches remain.
    max_by_key: dict[str, int] = {
        **{
            key: 2
            for _category, key, _label, _value, _prices, _rule_label in _DELTA_TECH_CANONICAL
        },
        **{key: 2 for key, _label, _prices in _DELTA_ENTERTAIN_CANONICAL},
        **{
            _sweet_canonical_key(prefix, mode): 2
            for prefix, _category in _SWEET_PREFIX_CATEGORIES
            for mode in ("female", "male", "any")
        },
    }

    canonical_labels: dict[str, str] = {
        key: rule_label
        for _category, key, _label, _value, _prices, rule_label in _DELTA_TECH_CANONICAL
    }
    canonical_labels.update({key: label for key, label, _prices in _DELTA_ENTERTAIN_CANONICAL})
    for prefix, _category in _SWEET_PREFIX_CATEGORIES:
        canonical_labels.update({
            _sweet_canonical_key(prefix, "female"): f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜女陪",
            _sweet_canonical_key(prefix, "male"): f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜男陪",
            _sweet_canonical_key(prefix, "any"): f"{_SWEET_GAME_LABELS[prefix]}｜甜蜜單｜不限",
        })

    active = load_active_overrides()
    changed = False
    for key, maximum in max_by_key.items():
        item = active.get(key)
        if not item:
            continue

        original_payload = dict(item.get("payload") or {})
        payload = dict(original_payload)
        payload.update({
            "label": canonical_labels[key],
            "required_staff_count": "player_count",
            "player_count_enabled": True,
            "min_player_count": 1,
            "max_player_count": int(maximum),
            "price_multiply_player_count": False,
            "max_specified_count": int(maximum),
            "catalog_group_label": "",
        })
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
            # A concurrent manager save wins. The next process restart will retry
            # against the newly-active version instead of masking it in memory.
            print(
                f"[companion-count] override migration skipped {key}: {exc}",
                flush=True,
            )

    if changed:
        order_rules.invalidate_rule_override_cache()


def _refresh_derived_maps(orders, order_rules) -> None:
    # Rebuild label/category lookup entries for newly-created semantic Sweet rules.
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
    """Make count-neutral rules/catalog authoritative without read-time overlays."""
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


# Kept as a compatibility import for older startup code. The catalog itself is now
# authoritative, so there is intentionally no Discord-only helper monkey patch.
def install_companion_count_discord_runtime_20261028() -> None:
    return None


__all__ = [
    "install_companion_count_catalog_cleanup_20261028",
    "install_companion_count_discord_runtime_20261028",
]
