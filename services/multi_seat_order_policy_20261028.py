from __future__ import annotations

from dataclasses import replace
from typing import Any


_INSTALLED = False

_SEAT_LABELS = {
    1: "單陪",
    2: "雙陪",
    3: "三陪",
    4: "四陪",
}

_BLACK_TIDE_VARIANTS = (
    ("basic_black_tide_entertain_1", "娛樂單陪", "basic_entertain_single", 1, 320),
    ("basic_black_tide_entertain_2", "娛樂雙陪", "basic_entertain_double", 2, 600),
    ("basic_black_tide_entertain_3", "娛樂三陪", "basic_entertain_double", 3, 900),
    ("basic_black_tide_entertain_4", "娛樂四陪", "basic_entertain_double", 4, 1200),
    ("basic_black_tide_tech_1", "技術單陪", "basic_tech_secret_single", 1, 400),
    ("basic_black_tide_tech_2", "技術雙陪", "basic_tech_secret_double", 2, 760),
    ("basic_black_tide_tech_3", "技術三陪", "basic_tech_secret_double", 3, 1140),
    ("basic_black_tide_tech_4", "技術四陪", "basic_tech_secret_double", 4, 1520),
)

# LoL technical tiers historically had NG/RK only in self-service. AR is hourly and
# follows the same tier price as NG until the owner publishes a separate AR price.
# Service point rewards default off for these new tiered variants so creating AR
# cannot bypass the currently disabled tiered-game point-benefit policy.
_LOL_TECH_ARAM_VARIANTS = (
    ("lol_master_aram", "lol_master_ng", "英雄聯盟｜大師陪｜ARAM"),
    ("lol_grandmaster_aram", "lol_grandmaster_ng", "英雄聯盟｜宗師陪｜ARAM"),
    ("lol_elite_aram", "lol_elite_ng", "英雄聯盟｜菁英陪｜ARAM"),
)

_LOL_TECH_ARAM_BY_NG_KEY = {
    template_key: new_key
    for new_key, template_key, _label in _LOL_TECH_ARAM_VARIANTS
}

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


def _install_black_tide_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    for key, label, template_key, staff_count, price in _BLACK_TIDE_VARIANTS:
        if key in ORDER_RULES:
            continue

        template = ORDER_RULES.get(template_key)
        if template is None:
            raise RuntimeError(f"missing Black Tide rule template: {template_key}")

        rule = replace(
            template,
            key=key,
            label=f"黑潮爆破｜{label}",
            price=int(price),
            required_staff_count=int(staff_count),
            player_count_enabled=False,
            price_multiply_player_count=False,
            max_specified_count=int(staff_count),
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
        rule = replace(
            template,
            key=key,
            label=label,
            point_benefits_allowed=False,
        )
        validate_rule_definition(key, rule)
        ORDER_RULES[key] = rule


def _black_tide_details() -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for key, label, _template_key, _staff_count, price in _BLACK_TIDE_VARIANTS:
        details.append(
            {
                "label": f"{label}｜{price}T / H",
                "value": key.removeprefix("basic_black_tide_"),
                "rule_key": key,
                "quantity_unit": "小時",
                "min_quantity": 1,
                "max_quantity": 24,
            }
        )
    return details


def _replace_or_append_group(groups: list[dict[str, Any]], label: str, details: list[dict[str, Any]]) -> None:
    for group in groups:
        if str(group.get("label") or "") == label:
            group["details"] = [dict(item) for item in details]
            return
    groups.append({"label": label, "details": [dict(item) for item in details]})


def _mode_sort_key(detail: dict[str, Any]) -> tuple[int, int]:
    value = str(detail.get("value") or "")
    if value.startswith("ng_"):
        mode_order = 0
    elif value.startswith("ranked_"):
        mode_order = 1
    elif value.startswith("aram_"):
        mode_order = 2
    else:
        mode_order = 9
    try:
        seat_count = int(detail.get("player_count") or value.rsplit("_", 1)[-1])
    except (TypeError, ValueError):
        seat_count = 99
    return mode_order, seat_count


def _patch_self_service_catalog() -> None:
    from services import orders

    desktop_groups = orders.SELF_SERVICE_ORDER_CATALOG.get("delta_desktop_basic", [])
    _replace_or_append_group(desktop_groups, "黑潮爆破", _black_tide_details())

    for group in orders.SELF_SERVICE_ORDER_CATALOG.get("steam", []):
        for detail in group.get("details", []):
            try:
                count = int(detail.get("player_count") or 1)
            except (TypeError, ValueError):
                continue
            if count in _SEAT_LABELS and str(detail.get("rule_key") or "") == "steam_play":
                detail["label"] = _SEAT_LABELS[count]

    for group in orders.SELF_SERVICE_ORDER_CATALOG.get("valorant", []):
        for detail in group.get("details", []):
            value = str(detail.get("value") or "")
            try:
                count = int(detail.get("player_count") or value.rsplit("_", 1)[-1])
            except (TypeError, ValueError):
                continue
            if count not in _SEAT_LABELS:
                continue
            if value.startswith("ng_"):
                detail["label"] = f"NG {_SEAT_LABELS[count]}"
            elif value.startswith("ranked_"):
                detail["label"] = f"RK {_SEAT_LABELS[count]}"
        group["details"] = sorted(group.get("details", []), key=_mode_sort_key)

    for group in orders.SELF_SERVICE_ORDER_CATALOG.get("lol", []):
        details = list(group.get("details", []))
        existing_rule_keys = {str(item.get("rule_key") or "") for item in details}

        for ng_key, aram_key in _LOL_TECH_ARAM_BY_NG_KEY.items():
            if ng_key not in existing_rule_keys or aram_key in existing_rule_keys:
                continue
            details.extend(
                {
                    "label": f"AR {_SEAT_LABELS[count]}",
                    "value": f"aram_{count}",
                    "rule_key": aram_key,
                    "player_count": count,
                    "quantity_unit": "小時",
                    "min_quantity": 1,
                    "max_quantity": 24,
                }
                for count in range(1, 5)
            )
            break

        for detail in details:
            value = str(detail.get("value") or "")
            try:
                count = int(detail.get("player_count") or value.rsplit("_", 1)[-1])
            except (TypeError, ValueError):
                continue
            if count not in _SEAT_LABELS:
                continue
            if value.startswith("ng_"):
                detail["label"] = f"NG {_SEAT_LABELS[count]}"
            elif value.startswith("ranked_"):
                detail["label"] = f"RK {_SEAT_LABELS[count]}"
            elif value.startswith("aram_"):
                detail["label"] = f"AR {_SEAT_LABELS[count]}"

        group["details"] = sorted(details, key=_mode_sort_key)


def _patch_loyalty_scope_aliases() -> None:
    from services import loyalty_benefits as loyalty

    aliases = getattr(loyalty, "_LOYALTY_SCOPE_FAMILY_ALIASES", None)
    if not isinstance(aliases, dict):
        return

    for key, _label, _template_key, _staff_count, _price in _BLACK_TIDE_VARIANTS:
        if "_entertain_" in key:
            aliases[key] = "basic_entertain"


def _point_rows() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    specs: dict[str, dict[str, Any]] = {}

    for tier, costs_by_seat in _POINT_COSTS.items():
        prefix = "entertain" if tier == "entertainment" else "tech"
        tier_text = "娛樂" if tier == "entertainment" else "技術"
        for seat_count in range(1, 5):
            seat_key = _SEAT_KEY_NAMES[seat_count]
            seat_text = _SEAT_LABELS[seat_count]
            small_cost, large_cost = costs_by_seat[seat_count]
            for size, cost, service_text in (
                ("small", small_cost, "30 分鐘／1 局"),
                ("large", large_cost, "1 小時／2 局"),
            ):
                key = f"{prefix}_{seat_key}_service_{size}"
                items.append(
                    {
                        "key": key,
                        "cost": int(cost),
                        "name": f"{tier_text}{seat_text}加贈｜{service_text}",
                    }
                )
                specs[key] = {
                    "kind": "service_bonus",
                    "service_tier": tier,
                    "seat_count": seat_count,
                    "bonus_size": size,
                    "summary": (
                        f"{tier_text}{seat_text}{seat_count} 位同步加贈 {service_text}；"
                        "店內吸收全部額外服務成本"
                    ),
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
    catalog.POINT_REDEEM_ITEMS_BY_KEY.update(
        {
            str(item["key"]): dict(item)
            for item in catalog.POINT_REDEEM_ITEMS
        }
    )

    for key in list(catalog.POINT_BENEFIT_SPECS):
        if _is_current_seat_service_key(str(key)):
            catalog.POINT_BENEFIT_SPECS.pop(key, None)
    catalog.POINT_BENEFIT_SPECS.update(
        {key: dict(value) for key, value in new_specs.items()}
    )

    catalog.ALL_POINT_BENEFIT_SPECS.clear()
    catalog.ALL_POINT_BENEFIT_SPECS.update(
        {
            **catalog.LEGACY_POINT_BENEFIT_SPECS,
            **catalog.POINT_BENEFIT_SPECS,
        }
    )


def install_multi_seat_order_policy_20261028() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_black_tide_rules()
    _install_lol_tech_aram_rules()
    _patch_self_service_catalog()
    _patch_loyalty_scope_aliases()
    _replace_point_service_catalog()
    _INSTALLED = True
