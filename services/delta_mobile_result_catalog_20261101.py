from __future__ import annotations

from services.order_rules import (
    DELTA_MOBILE_GAME_ROLE,
    PROTECTOR_ROLES,
    OrderRule,
)


MOBILE_TECH_RULE_KEYS = frozenset({
    "basic_mobile_tech_secret_single",
    "basic_mobile_tech_secret_double",
    "basic_mobile_tech_topsecret_single",
    "basic_mobile_tech_topsecret_double",
})


# Handheld Delta Force self-service is intentionally result-based for guard orders.
# Time-based products remain only for entertainment / sweet / teaching services.
_MOBILE_RESULT_GROUPS = (
    {
        "key": "mobile_trial",
        "label": "護航體驗單",
        "selector_label": "方案",
        "description": "三角洲手遊護航入門方案；依累積帶出金額完成。",
        "variants": (
            {
                "key": "delta_mobile_trial_777w",
                "label": "777W",
                "value": "777w",
                "price": 400,
                "note": "累積帶出 777W。",
                "vip_discount_allowed": False,
            },
            {
                "key": "delta_mobile_trial_1688w",
                "label": "1688W",
                "value": "1688w",
                "price": 800,
                "note": "累積帶出 1688W。",
                "vip_discount_allowed": False,
            },
        ),
    },
    {
        "key": "mobile_guarantee",
        "label": "護航保底單",
        "selector_label": "累積保底",
        "description": "依選擇方案提供累積帶出金額保底。",
        "variants": (
            {
                "key": "delta_mobile_guarantee_1500w",
                "label": "1500W",
                "value": "1500w",
                "price": 600,
                "note": "累積保底 1500W。",
            },
            {
                "key": "delta_mobile_guarantee_4200w",
                "label": "4200W",
                "value": "4200w",
                "price": 2000,
                "note": "累積保底 4200W。",
            },
            {
                "key": "delta_mobile_guarantee_110m",
                "label": "110M",
                "value": "110m",
                "price": 4000,
                "note": "累積保底 110M。",
            },
            {
                "key": "delta_mobile_guarantee_300m",
                "label": "300M",
                "value": "300m",
                "price": 10000,
                "note": "累積保底 300M。",
            },
        ),
    },
    {
        "key": "mobile_big_red",
        "label": "大紅單",
        "selector_label": "累積帶出",
        "description": "100萬以上的紅色物資計為大紅。",
        "variants": (
            {
                "key": "delta_mobile_big_red_1",
                "label": "1 大紅",
                "value": "1_red",
                "price": 1000,
                "note": "累積帶出 1 個大紅；100萬以上紅色物資計為大紅。",
            },
            {
                "key": "delta_mobile_big_red_5",
                "label": "5 大紅",
                "value": "5_red",
                "price": 4000,
                "note": "累積帶出 5 個大紅；100萬以上紅色物資計為大紅。",
            },
            {
                "key": "delta_mobile_big_red_10",
                "label": "10 大紅",
                "value": "10_red",
                "price": 7000,
                "note": "累積帶出 10 個大紅；100萬以上紅色物資計為大紅。",
            },
        ),
    },
    {
        "key": "mobile_babel",
        "label": "巴別塔限定",
        "selector_label": "方案",
        "description": "巴別塔結果型護航方案；依選擇內容完成後結單。",
        "variants": (
            {
                "key": "delta_mobile_babel_basic",
                "label": "基礎護航",
                "value": "basic",
                "price": 600,
                "note": "2 個沙色保險＋800W 保底。",
            },
            {
                "key": "delta_mobile_babel_advanced",
                "label": "進階護航",
                "value": "advanced",
                "price": 3000,
                "note": "累積 10 個沙色保險＋6000W 保底。",
            },
            {
                "key": "delta_mobile_babel_flagship",
                "label": "最強方案",
                "value": "flagship",
                "price": 5000,
                "note": "累積 20 個沙色保險＋100M 保底。",
            },
            {
                "key": "delta_mobile_babel_three_gods",
                "label": "三幻神挑戰",
                "value": "three_gods",
                "price": 5000,
                "note": "三幻神任一出現即結單；不出不結。",
            },
        ),
    },
)


def _set_code_rule(order_rules, key: str, rule: OrderRule) -> None:
    """Register a system-owned rule in both effective and immutable maps."""
    order_rules.validate_rule_definition(key, rule)
    dict.__setitem__(order_rules.ORDER_RULES, key, rule)
    order_rules._BASE_ORDER_RULES[key] = rule


def _install_rules() -> None:
    from services import order_rules

    for group in _MOBILE_RESULT_GROUPS:
        group_label = str(group["label"])
        for variant in group["variants"]:
            key = str(variant["key"])
            rule = OrderRule(
                category="delta_mobile_basic",
                key=key,
                label=f"三角洲手遊｜{group_label}｜{variant['label']}",
                pricing_type="fixed",
                price=int(variant["price"]),
                unit_label="單",
                allowed_roles=PROTECTOR_ROLES,
                required_staff_count=2,
                min_quantity=1,
                max_quantity=1,
                allow_specify=False,
                catalog_group_label=group_label,
                vip_discount_allowed=bool(
                    variant.get("vip_discount_allowed", True)
                ),
                point_benefits_allowed=True,
                min_protector_count=2,
                note=str(variant.get("note") or ""),
                required_game_roles=DELTA_MOBILE_GAME_ROLE,
            )
            _set_code_rule(order_rules, key, rule)


def _discord_group(group: dict) -> dict:
    return {
        "label": str(group["label"]),
        "details": [
            {
                "label": str(variant["label"]),
                "value": str(variant["value"]),
                "rule_key": str(variant["key"]),
                "quantity_unit": "單",
                "min_quantity": 1,
                "max_quantity": 1,
            }
            for variant in group["variants"]
        ],
    }


def _drop_mobile_tech_groups(groups: list[dict]) -> list[dict]:
    result: list[dict] = []
    for group in groups:
        details = [
            dict(detail)
            for detail in group.get("details", [])
            if str(detail.get("rule_key") or "") not in MOBILE_TECH_RULE_KEYS
        ]
        if not details:
            continue
        cloned = dict(group)
        cloned["details"] = details
        result.append(cloned)
    return result


def _install_discord_catalog() -> None:
    from services import order_rules, orders

    # Remove the handheld technical-hourly product from both the current split
    # category and the legacy aggregate catalog. Historical rule keys remain
    # resolvable for old order snapshots, but no new self-service path exposes them.
    for category in ("basic", "delta_mobile_basic"):
        existing = list(orders.SELF_SERVICE_ORDER_CATALOG.get(category, []))
        orders.SELF_SERVICE_ORDER_CATALOG[category] = _drop_mobile_tech_groups(existing)

    mobile_groups = orders.SELF_SERVICE_ORDER_CATALOG.setdefault(
        "delta_mobile_basic",
        [],
    )
    new_group_labels = {str(group["label"]) for group in _MOBILE_RESULT_GROUPS}
    new_rule_keys = {
        str(variant["key"])
        for group in _MOBILE_RESULT_GROUPS
        for variant in group["variants"]
    }

    # Idempotent re-install: discard an older copy before inserting the approved
    # groups in front of entertainment / sweet / teaching services.
    mobile_groups[:] = [
        group
        for group in mobile_groups
        if str(group.get("label") or "") not in new_group_labels
        and not any(
            str(detail.get("rule_key") or "") in new_rule_keys
            for detail in group.get("details", [])
        )
    ]

    anchor = next(
        (
            index
            for index, group in enumerate(mobile_groups)
            if str(group.get("label") or "") == "娛樂陪"
        ),
        len(mobile_groups),
    )
    mobile_groups[anchor:anchor] = [
        _discord_group(group)
        for group in _MOBILE_RESULT_GROUPS
    ]

    orders.CATALOG_HIDDEN_RULE_KEYS.update(MOBILE_TECH_RULE_KEYS)
    orders.ORDER_ITEMS_BY_CATEGORY["delta_mobile_basic"] = [
        rule.label
        for rule in order_rules.get_rules_by_category("delta_mobile_basic")
        if rule.key not in orders.CATALOG_HIDDEN_RULE_KEYS
    ]
    orders.ORDER_RULE_KEY_BY_LABEL.update({
        rule.label: rule.key
        for rule in order_rules.get_rules_by_category("delta_mobile_basic")
    })
    orders.ORDER_ITEM_TO_CATEGORY.update({
        rule.label: rule.category
        for rule in order_rules.get_rules_by_category("delta_mobile_basic")
    })


def mobile_result_web_group_specs() -> list[dict]:
    return [
        {
            "key": str(group["key"]),
            "category": "delta_mobile_basic",
            "label": str(group["label"]),
            "selector_label": str(group["selector_label"]),
            "description": str(group["description"]),
            "variants": [
                (str(variant["key"]), str(variant["label"]))
                for variant in group["variants"]
            ],
        }
        for group in _MOBILE_RESULT_GROUPS
    ]


def install_delta_mobile_result_web_catalog_20261101() -> None:
    """Patch the already-imported Web storefront group list."""
    from web.app.services import order_groups

    order_groups.HIDDEN_PUBLIC_RULE_KEYS.update(MOBILE_TECH_RULE_KEYS)

    new_specs = mobile_result_web_group_specs()
    new_keys = {str(spec["key"]) for spec in new_specs}
    new_labels = {str(spec["label"]) for spec in new_specs}

    order_groups.GROUP_SPECS[:] = [
        spec
        for spec in order_groups.GROUP_SPECS
        if str(spec.get("key") or "") != "tech_play_mobile"
        and str(spec.get("key") or "") not in new_keys
        and not (
            str(spec.get("category") or "") == "delta_mobile_basic"
            and str(spec.get("label") or "") in new_labels
        )
    ]

    anchor = next(
        (
            index
            for index, spec in enumerate(order_groups.GROUP_SPECS)
            if str(spec.get("key") or "") == "entertain_mobile"
        ),
        len(order_groups.GROUP_SPECS),
    )
    order_groups.GROUP_SPECS[anchor:anchor] = new_specs


def install_delta_mobile_result_catalog_20261101() -> None:
    """Install approved handheld Delta Force result products and Discord catalog."""
    _install_rules()
    _install_discord_catalog()


__all__ = [
    "MOBILE_TECH_RULE_KEYS",
    "install_delta_mobile_result_catalog_20261101",
    "install_delta_mobile_result_web_catalog_20261101",
    "mobile_result_web_group_specs",
]
