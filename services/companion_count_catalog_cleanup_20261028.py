from __future__ import annotations

from dataclasses import replace


_INSTALLED = False
_DISCORD_RUNTIME_INSTALLED = False


_DELTA_TECH_CANONICAL = (
    (
        "delta_desktop_basic",
        "basic_tech_secret_single",
        "機密",
        "secret",
        {1: 400, 2: 750},
    ),
    (
        "delta_desktop_basic",
        "basic_tech_topsecret_single",
        "絕密",
        "topsecret",
        {1: 450, 2: 850},
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_secret_single",
        "機密",
        "secret",
        {1: 380, 2: 760},
    ),
    (
        "delta_mobile_basic",
        "basic_mobile_tech_topsecret_single",
        "絕密",
        "topsecret",
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
    # EffectiveOrderRules is a dict subclass. Update both its backing entry and the
    # immutable fallback map so get_base_rule / manager override reads agree.
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
    # Keep the historical *_double keys untouched. New Discord checkout uses the
    # single canonical rule plus an independent companion-count control.
    for _category, key, _label, _value, prices in _DELTA_TECH_CANONICAL:
        rule = order_rules.ORDER_RULES.get(key)
        if rule is None:
            raise RuntimeError(f"missing Delta technical rule: {key}")
        migrated = _as_selectable_count_rule(rule, maximum=2)
        order_rules.validate_rule_definition(key, migrated)
        _set_code_rule(order_rules, key, migrated)
        multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = dict(prices)


def _sweet_canonical_key(prefix: str, mode: str) -> str:
    return f"{prefix}_sweet_{mode}"


def _install_sweet_canonical_rules(order_rules, multi_seat) -> None:
    """Add count-neutral Sweet rules without rewriting historical fixed-seat keys."""
    for prefix, _category in _SWEET_PREFIX_CATEGORIES:
        specs = (
            ("female", f"{prefix}_sweet_female_single", "女陪", 520),
            ("male", f"{prefix}_sweet_male_single", "男陪", 520),
            ("any", f"{prefix}_sweet_double_any", "不限", 520),
        )
        for mode, template_key, semantic_label, one_seat_price in specs:
            key = _sweet_canonical_key(prefix, mode)
            if dict.__contains__(order_rules.ORDER_RULES, key):
                rule = dict.__getitem__(order_rules.ORDER_RULES, key)
            else:
                template = order_rules.ORDER_RULES.get(template_key)
                if template is None:
                    raise RuntimeError(f"missing sweet companion template: {template_key}")
                game_label = str(template.label).split("｜甜蜜單｜", 1)[0]
                rule = replace(
                    template,
                    key=key,
                    label=f"{game_label}｜甜蜜單｜{semantic_label}",
                    price=int(one_seat_price),
                    catalog_group_label="甜蜜單",
                )
            rule = _as_selectable_count_rule(rule, maximum=2)
            order_rules.validate_rule_definition(key, rule)
            _set_code_rule(order_rules, key, rule)
            multi_seat.PLAYER_COUNT_PRICE_TABLES[key] = {1: 520, 2: 1314}


def _install_effective_rule_normalizer(order_rules) -> None:
    rules = order_rules.ORDER_RULES
    if getattr(rules, "_companion_count_catalog_cleanup_installed", False):
        return

    structural_keys = {
        key
        for _category, key, _label, _value, _prices in _DELTA_TECH_CANONICAL
    }
    structural_keys.update(
        _sweet_canonical_key(prefix, mode)
        for prefix, _category in _SWEET_PREFIX_CATEGORIES
        for mode in ("female", "male", "any")
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


def _discord_detail_rows(category: str | None, group_label: str | None) -> list[dict] | None:
    category_text = str(category or "")
    group_text = str(group_label or "")

    if group_text == "技術陪" and category_text in {"delta_desktop_basic", "delta_mobile_basic"}:
        return [
            {
                "label": label,
                "value": value,
                "rule_key": key,
                "quantity_unit": "小時",
                "min_quantity": 1,
                "max_quantity": 24,
                "item": label,
            }
            for row_category, key, label, value, _prices in _DELTA_TECH_CANONICAL
            if row_category == category_text
        ]

    if group_text == "甜蜜單":
        prefix = next(
            (prefix for prefix, mapped_category in _SWEET_PREFIX_CATEGORIES if mapped_category == category_text),
            None,
        )
        if prefix is not None:
            return [
                {
                    "label": "女陪",
                    "value": "female",
                    "rule_key": _sweet_canonical_key(prefix, "female"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                    "item": "女陪",
                },
                {
                    "label": "男陪",
                    "value": "male",
                    "rule_key": _sweet_canonical_key(prefix, "male"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                    "item": "男陪",
                },
                {
                    "label": "不限",
                    "value": "any",
                    "rule_key": _sweet_canonical_key(prefix, "any"),
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                    "item": "不限",
                },
            ]

    return None


def install_companion_count_discord_runtime_20261028() -> None:
    """Collapse count-duplicated Discord specs without changing historical catalogs.

    The Web/admin catalog and old selector values remain intact for compatibility.
    Discord self-service gets semantic specs and uses the existing companion-count
    control as the only customer-facing seat-count source.
    """
    global _DISCORD_RUNTIME_INSTALLED
    if _DISCORD_RUNTIME_INSTALLED:
        return

    from services import order_runtime, orders, self_service_selection_state, self_service_ui_runtime

    original_details = orders.get_order_item_details_for_group
    original_detail = orders.get_order_item_detail_for_selection

    def discord_details(category, group_label):
        rows = _discord_detail_rows(category, group_label)
        if rows is not None:
            return [dict(item) for item in rows]
        return original_details(category, group_label)

    def discord_detail(category, group_label, detail_value):
        rows = _discord_detail_rows(category, group_label)
        if rows is not None:
            target = str(detail_value or "")
            return next(
                (dict(item) for item in rows if str(item.get("value") or "") == target),
                None,
            )
        return original_detail(category, group_label, detail_value)

    # These modules import the helpers directly. Patch only their Discord runtime
    # references; services.orders itself intentionally keeps the legacy catalog so
    # historical Web selections and old tickets remain resolvable.
    order_runtime.get_order_item_details_for_group = discord_details
    order_runtime.get_order_item_detail_for_selection = discord_detail
    self_service_selection_state.get_order_item_details_for_group = discord_details
    self_service_ui_runtime.get_order_item_detail_for_selection = discord_detail

    _DISCORD_RUNTIME_INSTALLED = True


def install_companion_count_catalog_cleanup_20261028() -> None:
    """Install count-neutral business rules while retaining historical rule keys."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import multi_seat_order_policy_20261028 as multi_seat
    from services import order_rules

    _install_delta_tech_count_rules(order_rules, multi_seat)
    _install_sweet_canonical_rules(order_rules, multi_seat)
    _install_effective_rule_normalizer(order_rules)
    _INSTALLED = True


__all__ = [
    "install_companion_count_catalog_cleanup_20261028",
    "install_companion_count_discord_runtime_20261028",
]
