from __future__ import annotations

from dataclasses import replace
from typing import Any


_INSTALLED = False
_PRICE_PATCHED = False
_POINT_POLICY_PATCHED = False

_SEAT_LABELS = {
    1: "單陪",
    2: "雙陪",
    3: "三陪",
    4: "四陪",
}

# Historical Black Tide keys stay resolvable. New checkout uses the two canonical
# rules below and chooses 1-4 companions through the shared player-count control.
_BLACK_TIDE_LEGACY_VARIANTS = (
    ("basic_black_tide_entertain_1", "娛樂單陪", "basic_entertain_single", 1, 320),
    ("basic_black_tide_entertain_2", "娛樂雙陪", "basic_entertain_double", 2, 600),
    ("basic_black_tide_entertain_3", "娛樂三陪", "basic_entertain_double", 3, 900),
    ("basic_black_tide_entertain_4", "娛樂四陪", "basic_entertain_double", 4, 1200),
    ("basic_black_tide_tech_1", "技術單陪", "basic_tech_secret_single", 1, 400),
    ("basic_black_tide_tech_2", "技術雙陪", "basic_tech_secret_double", 2, 760),
    ("basic_black_tide_tech_3", "技術三陪", "basic_tech_secret_double", 3, 1140),
    ("basic_black_tide_tech_4", "技術四陪", "basic_tech_secret_double", 4, 1520),
)

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

# Explicit seat-price tables. Even when values happen to be linear (Steam), keeping
# the table explicit prevents future products from silently assuming base x people.
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

# Service-type point rewards are a product-rule policy, not a UI exception. Cash
# coupons / free-specify and all other point products remain governed by the normal
# point_benefits_allowed flag.
SERVICE_POINT_BENEFIT_RULE_OVERRIDES: dict[str, bool] = {}

_POINT_COSTS = {
    "entertainment": {
        1: (80, 140),
        2: (160, 280),
        3: (240, 420),
        4: (320, 560),
    },
    "technical": {
        1: (100, 180),
        2: (200, 360),
        3: (300, 540),
        4: (400, 720),
    },
}

_SEAT_KEY_NAMES = {
    1: "single",
    2: "double",
    3: "triple",
    4: "quad",
}


def get_player_count_price_table(rule_or_key) -> dict[int, int] | None:
    key = str(getattr(rule_or_key, "key", rule_or_key) or "")
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
    key = str(getattr(rule, "key", "") or "")
    return bool(SERVICE_POINT_BENEFIT_RULE_OVERRIDES.get(key, True))


def _install_delta_companion_type_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    canonical_keys = (
        "basic_entertain_single",
        "basic_entertain_female_single",
        "basic_entertain_male_single",
        "basic_mobile_entertain_single",
        "basic_mobile_entertain_female_single",
        "basic_mobile_entertain_male_single",
    )
    for key in canonical_keys:
        rule = ORDER_RULES.get(key)
        if rule is None:
            continue
        new_rule = replace(
            rule,
            required_staff_count="player_count",
            player_count_enabled=True,
            min_player_count=1,
            max_player_count=2,
            price_multiply_player_count=False,
            max_specified_count=2,
        )
        validate_rule_definition(key, new_rule)
        ORDER_RULES[key] = new_rule


def _install_black_tide_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    for key, label, template_key, staff_count, price in _BLACK_TIDE_LEGACY_VARIANTS:
        if key in ORDER_RULES:
            continue
        template = ORDER_RULES.get(template_key)
        if template is None:
            raise RuntimeError(f"missing Black Tide legacy template: {template_key}")
        rule = replace(
            template,
            key=key,
            label=f"黑潮爆破｜{label}",
            price=int(price),
            required_staff_count=int(staff_count),
            player_count_enabled=False,
            price_multiply_player_count=False,
            max_specified_count=int(staff_count),
            catalog_group_label="黑潮爆破",
        )
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule

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
            raise RuntimeError(f"missing LoL AR rule template: {template_key}")
        rule = replace(template, key=key, label=label)
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule


def _install_service_point_rule_switches() -> None:
    from services.order_rules import ORDER_RULES

    for key, rule in ORDER_RULES.items():
        category = str(getattr(rule, "category", "") or "")
        if category in {"lol", "valorant", "apex"}:
            SERVICE_POINT_BENEFIT_RULE_OVERRIDES[str(key)] = False


def _replace_or_append_group(groups: list[dict[str, Any]], label: str, details: list[dict[str, Any]]) -> None:
    for group in groups:
        if str(group.get("label") or "") == label:
            group["details"] = [dict(item) for item in details]
            return
    groups.append({"label": label, "details": [dict(item) for item in details]})


def _collapse_group_by_rule(groups: list[dict[str, Any]], *, mode_labels: dict[str, str]) -> None:
    for group in groups:
        seen: set[str] = set()
        collapsed: list[dict[str, Any]] = []
        for detail in list(group.get("details", [])):
            rule_key = str(detail.get("rule_key") or "")
            if not rule_key or rule_key in seen:
                continue
            seen.add(rule_key)
            value = str(detail.get("value") or "")
            mode = value.split("_", 1)[0]
            item = dict(detail)
            item.pop("player_count", None)
            item["value"] = mode
            item["label"] = mode_labels.get(mode, str(detail.get("label") or mode))
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
        mode_labels={"ng": "NG", "ranked": "RK"},
    )

    custom_groups = orders.SELF_SERVICE_ORDER_CATALOG.get("custom", [])
    _replace_or_append_group(
        custom_groups,
        "自訂",
        [{
            "label": "自訂",
            "value": "custom",
            "rule_key": "custom_custom_order",
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        }],
    )


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


def _patch_loyalty_scope_aliases() -> None:
    from services import loyalty_benefits as loyalty

    aliases = getattr(loyalty, "_LOYALTY_SCOPE_FAMILY_ALIASES", None)
    if not isinstance(aliases, dict):
        return
    for key in (
        "basic_black_tide_entertain",
        "basic_black_tide_entertain_1",
        "basic_black_tide_entertain_2",
        "basic_black_tide_entertain_3",
        "basic_black_tide_entertain_4",
    ):
        aliases[key] = "basic_entertain"


def _point_rows() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    specs: dict[str, dict[str, Any]] = {}
    for tier, costs_by_seat in _POINT_COSTS.items():
        prefix = "entertain" if tier == "entertainment" else "tech"
        tier_text = "娛樂" if tier == "entertainment" else "技術"
        for seat_count in range(1, 5):
            seat_key = _SEAT_KEY_NAMES[seat_count]
            small_cost, large_cost = costs_by_seat[seat_count]
            for size, cost, service_text in (
                ("small", small_cost, "30 分鐘／1 局"),
                ("large", large_cost, "1 小時／2 局"),
            ):
                key = f"{prefix}_{seat_key}_service_{size}"
                items.append({
                    "key": key,
                    "cost": int(cost),
                    "name": f"{tier_text}{seat_count}陪加贈｜{service_text}",
                })
                specs[key] = {
                    "kind": "service_bonus",
                    "service_tier": tier,
                    "seat_count": seat_count,
                    "bonus_size": size,
                    "summary": f"{tier_text}{seat_count}陪同步加贈 {service_text}；店內吸收全部額外服務成本",
                }
    return items, specs


def _replace_point_service_catalog() -> None:
    from services import point_benefit_catalog as catalog

    new_items, new_specs = _point_rows()
    new_keys = set(new_specs)

    def _is_current_seat_service_key(key: str) -> bool:
        if key in new_keys:
            return True
        return any(
            key.startswith(f"{prefix}_{seat_key}_service_")
            for prefix in ("entertain", "tech")
            for seat_key in _SEAT_KEY_NAMES.values()
        )

    non_service_items = [
        dict(item)
        for item in catalog.POINT_REDEEM_ITEMS
        if not _is_current_seat_service_key(str(item.get("key") or ""))
    ]
    catalog.POINT_REDEEM_ITEMS[:] = non_service_items + [dict(item) for item in new_items]
    catalog.POINT_REDEEM_ITEMS_BY_KEY.clear()
    catalog.POINT_REDEEM_ITEMS_BY_KEY.update({
        str(item["key"]): dict(item)
        for item in catalog.POINT_REDEEM_ITEMS
    })
    for key in list(catalog.POINT_BENEFIT_SPECS):
        if _is_current_seat_service_key(str(key)):
            catalog.POINT_BENEFIT_SPECS.pop(key, None)
    catalog.POINT_BENEFIT_SPECS.update({key: dict(value) for key, value in new_specs.items()})
    catalog.ALL_POINT_BENEFIT_SPECS.clear()
    catalog.ALL_POINT_BENEFIT_SPECS.update({
        **catalog.LEGACY_POINT_BENEFIT_SPECS,
        **catalog.POINT_BENEFIT_SPECS,
    })


def _install_price_table_runtime() -> None:
    global _PRICE_PATCHED
    if _PRICE_PATCHED:
        return

    from services import order_rules

    original = order_rules.calculate_price

    def calculate_price(rule, *, quantity=None, player_count=None, specified_roles=None, staff_adjustments=None):
        table = get_player_count_price_table(rule)
        if not table:
            return original(
                rule,
                quantity=quantity,
                player_count=player_count,
                specified_roles=specified_roles,
                staff_adjustments=staff_adjustments,
            )
        count = normalize_rule_player_count(rule, player_count)
        if count not in table:
            raise ValueError(f"{rule.label} 不支援 {count} 位陪玩")
        priced_rule = replace(
            rule,
            price=int(table[count]),
            price_multiply_player_count=False,
        )
        return original(
            priced_rule,
            quantity=quantity,
            player_count=count,
            specified_roles=specified_roles,
            staff_adjustments=staff_adjustments,
        )

    order_rules.calculate_price = calculate_price
    order_rules._multi_seat_price_table_20261028 = PLAYER_COUNT_PRICE_TABLES
    _PRICE_PATCHED = True


def _install_service_point_policy_runtime() -> None:
    global _POINT_POLICY_PATCHED
    if _POINT_POLICY_PATCHED:
        return

    from services import self_service_point_benefit_policy as point_policy

    original_check = point_policy.check_order_point_benefit_allowed

    def check_order_point_benefit_allowed(rule, benefit, data: dict | None = None):
        allowed, reason = original_check(rule, benefit, data)
        if not allowed:
            return allowed, reason
        spec = dict(benefit or {})
        if str(spec.get("kind") or "") == "service_bonus" and not is_service_point_benefit_enabled(rule):
            return False, "這個商品目前暫停使用點數加時／加局券。"
        return True, ""

    point_policy.check_order_point_benefit_allowed = check_order_point_benefit_allowed
    _POINT_POLICY_PATCHED = True


def install_multi_seat_order_policy_20261028() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_delta_companion_type_rules()
    _install_black_tide_rules()
    _install_lol_tech_aram_rules()
    _install_service_point_rule_switches()
    _patch_self_service_catalog()
    _refresh_order_derived_maps()
    _patch_loyalty_scope_aliases()
    _replace_point_service_catalog()
    _install_price_table_runtime()
    _install_service_point_policy_runtime()
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
