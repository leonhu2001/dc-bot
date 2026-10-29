from __future__ import annotations

from dataclasses import replace
from typing import Any

from services.unified_service_point_policy import is_rule_service_bonus_supported


_INSTALLED = False

_SEAT_LABELS = {
    1: "單陪",
    2: "雙陪",
    3: "三陪",
    4: "四陪",
}

# Historical Black Tide keys stay resolvable. New checkout uses the two canonical
# rules below and chooses 1-4 companions through the shared player-count control.
_BLACK_TIDE_LEGACY_VARIANTS: tuple = ()

_BLACK_TIDE_CANONICAL = (
    (
        "basic_black_tide_entertain",
        "黑潮爆破｜娛樂陪",
        "basic_entertain_single",
        {1: 320, 2: 600, 3: 900, 4: 1200},
    ),
    (
        "basic_black_tide_tech",
        "黑潮爆破｜技術陪",
        "basic_tech_secret_single",
        {1: 400, 2: 760, 3: 1140, 4: 1520},
    ),
)

# LoL technical tiers historically had NG/RK only. AR is hourly and follows that
# tier's NG price until a separate AR price is published.
_LOL_TECH_ARAM_VARIANTS = (
    ("lol_master_aram", "lol_master_ng", "英雄聯盟｜大師陪｜ARAM"),
    ("lol_grandmaster_aram", "lol_grandmaster_ng", "英雄聯盟｜宗師陪｜ARAM"),
    ("lol_elite_aram", "lol_elite_ng", "英雄聯盟｜菁英陪｜ARAM"),
)

_LOL_TECH_ARAM_BY_NG_KEY = {
    template_key: new_key
    for new_key, template_key, _label in _LOL_TECH_ARAM_VARIANTS
}

# Kept as compatibility metadata for callers that still inspect this map. Pricing
# itself is authoritative on OrderRule.player_count_prices and calculate_price()
# now reads that field directly; this table no longer patches calculate_price.
PLAYER_COUNT_PRICE_TABLES: dict[str, dict[int, int]] = {
    "basic_entertain_single": {1: 320, 2: 600},
    "basic_entertain_female_single": {1: 320, 2: 600},
    "basic_entertain_male_single": {1: 320, 2: 600},
    "basic_mobile_entertain_single": {1: 320, 2: 600},
    "basic_mobile_entertain_female_single": {1: 320, 2: 600},
    "basic_mobile_entertain_male_single": {1: 320, 2: 600},
    "basic_black_tide_entertain": {1: 320, 2: 600, 3: 900, 4: 1200},
    "basic_black_tide_tech": {1: 400, 2: 760, 3: 1140, 4: 1520},
    "steam_play": {1: 320, 2: 640, 3: 960, 4: 1280},
}

# Compatibility map only. Eligibility is now calculated from the formal rule by
# unified_service_point_policy instead of being installed as a runtime override.
SERVICE_POINT_BENEFIT_RULE_OVERRIDES: dict[str, bool] = {}


def get_player_count_price_table(rule_or_key) -> dict[int, int] | None:
    direct = getattr(rule_or_key, "player_count_prices", None)
    if direct:
        return {int(key): int(value) for key, value in dict(direct).items()}
    key = str(getattr(rule_or_key, "key", rule_or_key) or "")
    try:
        from services.order_rules import ORDER_RULES

        rule = ORDER_RULES.get(key)
        if rule is not None and getattr(rule, "player_count_prices", None):
            return {int(k): int(v) for k, v in dict(rule.player_count_prices).items()}
    except Exception:
        pass
    table = PLAYER_COUNT_PRICE_TABLES.get(key)
    return dict(table) if table else None


def get_rule_player_count_bounds(rule) -> tuple[int, int, int, bool]:
    """Return min, max, default and whether the customer can change the count."""
    if rule is None:
        return 1, 1, 1, False

    if bool(getattr(rule, "player_count_enabled", False)):
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum_raw = getattr(rule, "max_player_count", None)
        maximum = int(maximum_raw) if maximum_raw is not None else minimum
        maximum = max(minimum, maximum)
        return minimum, maximum, minimum, maximum > minimum

    required = getattr(rule, "required_staff_count", 1)
    try:
        fixed = max(1, int(required or 1))
    except (TypeError, ValueError):
        fixed = 1
    return fixed, fixed, fixed, False


def normalize_rule_player_count(rule, value: Any = None) -> int:
    minimum, maximum, default, _selectable = get_rule_player_count_bounds(rule)
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    if count < minimum or count > maximum:
        return default
    return count


def is_service_point_benefit_enabled(rule) -> bool:
    """Compatibility entry point backed by the canonical formal-rule policy."""

    return bool(is_rule_service_bonus_supported(rule))


def _install_black_tide_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    for key, label, template_key, price_table in _BLACK_TIDE_CANONICAL:
        template = ORDER_RULES.get(template_key)
        if template is None:
            raise RuntimeError(f"missing Black Tide canonical template: {template_key}")
        if key in ORDER_RULES:
            continue
        rule = replace(
            template,
            key=key,
            label=label,
            price=int(price_table[1]),
            required_staff_count="player_count",
            player_count_enabled=True,
            min_player_count=1,
            max_player_count=4,
            price_multiply_player_count=False,
            player_count_prices=dict(price_table),
            max_specified_count=4,
            catalog_group_label="黑潮爆破",
        )
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule


def _install_lol_tech_aram_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    for key, template_key, label in _LOL_TECH_ARAM_VARIANTS:
        if key in ORDER_RULES:
            continue
        template = ORDER_RULES.get(template_key)
        if template is None:
            raise RuntimeError(f"missing LoL AR canonical template: {template_key}")
        rule = replace(template, key=key, label=label)
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule


def _install_service_point_rule_switches() -> None:
    from services.order_rules import ORDER_RULES

    SERVICE_POINT_BENEFIT_RULE_OVERRIDES.clear()
    SERVICE_POINT_BENEFIT_RULE_OVERRIDES.update({
        str(key): bool(is_rule_service_bonus_supported(rule))
        for key, rule in ORDER_RULES.items()
    })


def _replace_or_append_group(groups: list[dict[str, Any]], label: str, details: list[dict[str, Any]]) -> None:
    for group in groups:
        if str(group.get("label") or "") == label:
            group["details"] = [dict(item) for item in details]
            return
    groups.append({"label": label, "details": [dict(item) for item in details]})


def _collapse_group_by_rule(groups: list[dict[str, Any]], *, mode_labels: dict[str, str]) -> None:
    """Collapse only actual gameplay rows; leave sweet/teaching/other groups intact."""
    for group in groups:
        source = list(group.get("details", []))
        if not source:
            continue
        modes = [str(item.get("value") or "").split("_", 1)[0] for item in source]
        if not all(mode in mode_labels for mode in modes):
            continue

        seen: set[str] = set()
        collapsed: list[dict[str, Any]] = []
        for detail, mode in zip(source, modes):
            rule_key = str(detail.get("rule_key") or "")
            if not rule_key or rule_key in seen:
                continue
            seen.add(rule_key)
            item = dict(detail)
            item.pop("player_count", None)
            item["value"] = mode
            item["label"] = mode_labels[mode]
            collapsed.append(item)
        group["details"] = collapsed


def _patch_self_service_catalog() -> None:
    from services import orders

    # Delta entertainment: third field is companion TYPE only. Count is separate.
    for category, keys in (
        (
            "delta_desktop_basic",
            (
                "basic_entertain_single",
                "basic_entertain_female_single",
                "basic_entertain_male_single",
            ),
        ),
        (
            "delta_mobile_basic",
            (
                "basic_mobile_entertain_single",
                "basic_mobile_entertain_female_single",
                "basic_mobile_entertain_male_single",
            ),
        ),
    ):
        groups = orders.SELF_SERVICE_ORDER_CATALOG.get(category, [])
        for group in groups:
            detail_keys = {str(item.get("rule_key") or "") for item in group.get("details", [])}
            if not any(key in detail_keys for key in keys):
                continue
            group["details"] = [
                {
                    "label": "不限",
                    "value": "single",
                    "rule_key": keys[0],
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "女陪",
                    "value": "female_single",
                    "rule_key": keys[1],
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
                {
                    "label": "男陪",
                    "value": "male_single",
                    "rule_key": keys[2],
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                },
            ]
            break

    desktop_groups = orders.SELF_SERVICE_ORDER_CATALOG.get("delta_desktop_basic", [])
    _replace_or_append_group(
        desktop_groups,
        "黑潮爆破",
        [
            {
                "label": "娛樂陪",
                "value": "entertain",
                "rule_key": "basic_black_tide_entertain",
                "quantity_unit": "小時",
                "min_quantity": 1,
                "max_quantity": 24,
            },
            {
                "label": "技術陪",
                "value": "tech",
                "rule_key": "basic_black_tide_tech",
                "quantity_unit": "小時",
                "min_quantity": 1,
                "max_quantity": 24,
            },
        ],
    )

    steam_groups = orders.SELF_SERVICE_ORDER_CATALOG.get("steam", [])
    _replace_or_append_group(
        steam_groups,
        "娛樂陪",
        [{
            "label": "娛樂陪",
            "value": "play",
            "rule_key": "steam_play",
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        }],
    )

    _collapse_group_by_rule(
        orders.SELF_SERVICE_ORDER_CATALOG.get("valorant", []),
        mode_labels={"ng": "NG", "ranked": "RK"},
    )

    lol_groups = orders.SELF_SERVICE_ORDER_CATALOG.get("lol", [])
    for group in lol_groups:
        details = list(group.get("details", []))
        rule_keys = {str(item.get("rule_key") or "") for item in details}
        for ng_key, aram_key in _LOL_TECH_ARAM_BY_NG_KEY.items():
            if ng_key in rule_keys and aram_key not in rule_keys:
                source = next(item for item in details if str(item.get("rule_key") or "") == ng_key)
                details.append({
                    **dict(source),
                    "label": "AR",
                    "value": "aram",
                    "rule_key": aram_key,
                    "quantity_unit": "小時",
                })
                break
        group["details"] = details
    _collapse_group_by_rule(
        lol_groups,
        mode_labels={"ng": "NG", "ranked": "RK", "aram": "AR"},
    )

    _collapse_group_by_rule(
        orders.SELF_SERVICE_ORDER_CATALOG.get("apex", []),
        mode_labels={"ng": "NG", "ranked": "積分"},
    )

    # Custom quick-order has its own existing 1-4 headcount selector that resolves
    # historical player_count detail metadata. Leave that catalog untouched.


def _refresh_order_derived_maps() -> None:
    from services import orders
    from services.order_rules import ORDER_RULES

    added_keys = {
        *(key for key, _label, _template, _count, _price in _BLACK_TIDE_LEGACY_VARIANTS),
        *(key for key, _label, _template, _prices in _BLACK_TIDE_CANONICAL),
        *(key for key, _template, _label in _LOL_TECH_ARAM_VARIANTS),
    }
    for key in added_keys:
        rule = ORDER_RULES.get(key)
        if rule is None:
            continue
        label = str(rule.label)
        orders.ORDER_RULE_KEY_BY_LABEL[label] = key
        orders.ORDER_ITEM_TO_CATEGORY[label] = str(rule.category)
        items = orders.ORDER_ITEMS_BY_CATEGORY.setdefault(str(rule.category), [])
        if label not in items:
            items.append(label)
        if bool(getattr(rule, "allow_specify", False)):
            orders.SPECIAL_COMPANION_ITEMS.add(label)
        maximum = getattr(rule, "max_quantity", None)
        if maximum is None or int(maximum or 1) > 1:
            orders.QUANTITY_SELECT_ITEMS.add(label)


def install_multi_seat_order_policy_20261028() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Current OrderRule definitions already own Delta/Steam player-count pricing.
    # Keep this compatibility module limited to the two still-missing rule families
    # and catalog presentation; do not replace calculate_price or point functions.
    _install_black_tide_rules()
    _install_lol_tech_aram_rules()
    _install_service_point_rule_switches()
    _patch_self_service_catalog()
    _refresh_order_derived_maps()
    _INSTALLED = True


__all__ = [
    "PLAYER_COUNT_PRICE_TABLES",
    "SERVICE_POINT_BENEFIT_RULE_OVERRIDES",
    "get_player_count_price_table",
    "get_rule_player_count_bounds",
    "normalize_rule_player_count",
    "is_service_point_benefit_enabled",
    "install_multi_seat_order_policy_20261028",
]