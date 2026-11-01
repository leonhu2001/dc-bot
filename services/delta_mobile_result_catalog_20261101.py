from __future__ import annotations

from types import MethodType

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

MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS = frozenset({
    "basic_mobile_one_companion_one_guard_secret",
    "basic_mobile_one_companion_one_guard_topsecret",
})

MOBILE_RETIRED_GROUP_LABELS = frozenset({
    "技術陪",
    "一陪一護",
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


def _install_mobile_group_selector_filter(orders) -> None:
    """Hide retired handheld groups without deleting their resolver data.

    ORDER_ITEM_GROUPS_BY_CATEGORY is a DynamicOrderItemGroups instance. Giving the
    instance its own get() keeps this visibility policy intact even when the product
    status subsystem later swaps the class-level get() implementation in place.
    """
    groups = orders.ORDER_ITEM_GROUPS_BY_CATEGORY
    if getattr(groups, "_delta_mobile_result_filter_installed", False):
        return

    def filtered_get(self, category, default=None):
        labels = orders.DynamicOrderItemGroups.get(self, category, default)
        if str(category or "") == "delta_mobile_basic":
            labels = [
                label
                for label in labels
                if str(label or "") not in MOBILE_RETIRED_GROUP_LABELS
            ]
        return labels

    groups.get = MethodType(filtered_get, groups)
    groups._delta_mobile_result_filter_installed = True


def _install_discord_catalog() -> None:
    from services import order_rules, orders

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

    # Keep old 技術陪 / 一陪一護 group data for historical and already-open
    # interactions. Only remove previous copies of the new result groups.
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

    _install_mobile_group_selector_filter(orders)

    orders.ORDER_ITEMS_BY_CATEGORY["delta_mobile_basic"] = [
        rule.label
        for rule in order_rules.get_rules_by_category("delta_mobile_basic")
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


def _filter_public_mobile_groups(groups: list[dict]) -> list[dict]:
    return [
        group
        for group in groups
        if not (
            str(group.get("category") or "") == "delta_mobile_basic"
            and (
                str(group.get("key") or "") == "tech_play_mobile"
                or str(group.get("label") or "") == "一陪一護"
            )
        )
    ]


def _install_public_web_entry_filter() -> None:
    """Hide retired groups on real customer routes while keeping internal resolvers.

    Only the route module's already-imported bindings are wrapped. The underlying
    order_catalog_cards service stays untouched so its cache identity/TTL contract
    remains exactly as before.
    """
    from web.app.routers import site

    if getattr(site, "_delta_mobile_result_filter_installed", False):
        return

    original_grouped = site.get_grouped_order_catalog
    original_cards = site.get_grouped_order_catalog_cards
    original_detail = site.get_order_group_detail

    def public_grouped(category="all"):
        return _filter_public_mobile_groups(list(original_grouped(category)))

    def public_cards(category="all"):
        return _filter_public_mobile_groups(list(original_cards(category)))

    def public_detail(group_key):
        if str(group_key or "") == "tech_play_mobile":
            return None
        detail = original_detail(group_key)
        if detail and (
            str(detail.get("category") or "") == "delta_mobile_basic"
            and str(detail.get("label") or "") == "一陪一護"
        ):
            return None
        return detail

    site.get_grouped_order_catalog = public_grouped
    site.get_grouped_order_catalog_cards = public_cards
    site.get_order_group_detail = public_detail
    site._delta_mobile_result_filter_installed = True


def install_delta_mobile_result_web_catalog_20261101() -> None:
    """Install new Web cards while hiding retired mobile entry points."""
    from web.app.services import order_groups

    # Do not delete tech_play_mobile from GROUP_SPECS. Keeping it as resolver data
    # preserves old snapshots and existing regression contracts; customer routes are
    # filtered below so no new customer can start the retired hourly product.
    new_specs = mobile_result_web_group_specs()
    new_keys = {str(spec["key"]) for spec in new_specs}
    new_labels = {str(spec["label"]) for spec in new_specs}

    order_groups.GROUP_SPECS[:] = [
        spec
        for spec in order_groups.GROUP_SPECS
        if str(spec.get("key") or "") not in new_keys
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
    _install_public_web_entry_filter()


def install_delta_mobile_result_catalog_20261101() -> None:
    """Install approved handheld Delta Force result products and Discord catalog."""
    _install_rules()
    _install_discord_catalog()


__all__ = [
    "MOBILE_ONE_COMPANION_ONE_GUARD_RULE_KEYS",
    "MOBILE_RETIRED_GROUP_LABELS",
    "MOBILE_TECH_RULE_KEYS",
    "install_delta_mobile_result_catalog_20261101",
    "install_delta_mobile_result_web_catalog_20261101",
    "mobile_result_web_group_specs",
]
