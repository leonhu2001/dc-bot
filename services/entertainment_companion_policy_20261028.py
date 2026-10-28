from __future__ import annotations

from dataclasses import replace
from typing import Any


_INSTALLED = False
_FINANCIAL_RUNTIME_INSTALLED = False


_VARIANT_SPECS = (
    {
        "base_single": "basic_entertain_single",
        "base_double": "basic_entertain_double",
        "family": "basic_entertain",
        "display_family": "娛樂陪〈端遊〉",
        "variants": (
            ("basic_entertain_female_single", "女單陪", ("female_companion",), 1),
            ("basic_entertain_male_single", "男單陪", ("male_companion",), 1),
            ("basic_entertain_female_double", "女雙陪", ("female_companion",), 2),
            ("basic_entertain_male_double", "男雙陪", ("male_companion",), 2),
        ),
    },
    {
        "base_single": "basic_mobile_entertain_single",
        "base_double": "basic_mobile_entertain_double",
        "family": "basic_mobile_entertain",
        "display_family": "娛樂陪〈手遊〉",
        "variants": (
            ("basic_mobile_entertain_female_single", "女單陪", ("female_companion",), 1),
            ("basic_mobile_entertain_male_single", "男單陪", ("male_companion",), 1),
            ("basic_mobile_entertain_female_double", "女雙陪", ("female_companion",), 2),
            ("basic_mobile_entertain_male_double", "男雙陪", ("male_companion",), 2),
        ),
    },
)


_NEW_POINT_ITEMS = (
    {"key": "entertain_single_service_small", "cost": 80, "name": "娛樂單陪加贈｜30 分鐘／1 局"},
    {"key": "entertain_single_service_large", "cost": 140, "name": "娛樂單陪加贈｜1 小時／2 局"},
    {"key": "entertain_double_service_small", "cost": 160, "name": "娛樂雙陪加贈｜30 分鐘／1 局"},
    {"key": "entertain_double_service_large", "cost": 280, "name": "娛樂雙陪加贈｜1 小時／2 局"},
    {"key": "tech_single_service_small", "cost": 110, "name": "技術單陪加贈｜30 分鐘／1 局"},
    {"key": "tech_single_service_large", "cost": 200, "name": "技術單陪加贈｜1 小時／2 局"},
    {"key": "tech_double_service_small", "cost": 220, "name": "技術雙陪加贈｜30 分鐘／1 局"},
    {"key": "tech_double_service_large", "cost": 400, "name": "技術雙陪加贈｜1 小時／2 局"},
)


_NEW_POINT_SPECS = {
    "entertain_single_service_small": {
        "kind": "service_bonus",
        "service_tier": "entertainment",
        "seat_count": 1,
        "bonus_size": "small",
        "summary": "娛樂單陪加贈 30 分鐘或 1 局；店內吸收額外服務成本",
    },
    "entertain_single_service_large": {
        "kind": "service_bonus",
        "service_tier": "entertainment",
        "seat_count": 1,
        "bonus_size": "large",
        "summary": "娛樂單陪加贈 1 小時或 2 局；店內吸收額外服務成本",
    },
    "entertain_double_service_small": {
        "kind": "service_bonus",
        "service_tier": "entertainment",
        "seat_count": 2,
        "bonus_size": "small",
        "summary": "娛樂雙陪兩位同步加贈 30 分鐘或 1 局；店內吸收兩位額外服務成本",
    },
    "entertain_double_service_large": {
        "kind": "service_bonus",
        "service_tier": "entertainment",
        "seat_count": 2,
        "bonus_size": "large",
        "summary": "娛樂雙陪兩位同步加贈 1 小時或 2 局；店內吸收兩位額外服務成本",
    },
    "tech_single_service_small": {
        "kind": "service_bonus",
        "service_tier": "technical",
        "seat_count": 1,
        "bonus_size": "small",
        "summary": "技術單陪加贈 30 分鐘或 1 局；店內吸收額外服務成本",
    },
    "tech_single_service_large": {
        "kind": "service_bonus",
        "service_tier": "technical",
        "seat_count": 1,
        "bonus_size": "large",
        "summary": "技術單陪加贈 1 小時或 2 局；店內吸收額外服務成本",
    },
    "tech_double_service_small": {
        "kind": "service_bonus",
        "service_tier": "technical",
        "seat_count": 2,
        "bonus_size": "small",
        "summary": "技術雙陪兩位同步加贈 30 分鐘或 1 局；店內吸收兩位額外服務成本",
    },
    "tech_double_service_large": {
        "kind": "service_bonus",
        "service_tier": "technical",
        "seat_count": 2,
        "bonus_size": "large",
        "summary": "技術雙陪兩位同步加贈 1 小時或 2 局；店內吸收兩位額外服務成本",
    },
}


_RETIRED_CURRENT_SERVICE_KEYS = (
    "entertain_service_small",
    "entertain_service_large",
    "tech_service_small",
    "tech_service_large",
)


def _install_gendered_rules() -> None:
    from services.order_rules import ORDER_RULES, validate_rule_definition

    for spec in _VARIANT_SPECS:
        single = ORDER_RULES.get(str(spec["base_single"]))
        double = ORDER_RULES.get(str(spec["base_double"]))
        if single is None or double is None:
            continue

        for key, detail_label, allowed_roles, staff_count in spec["variants"]:
            if key in ORDER_RULES:
                continue
            template = single if int(staff_count) == 1 else double
            rule = replace(
                template,
                key=str(key),
                label=f"{spec['display_family']}｜{detail_label}",
                allowed_roles=tuple(allowed_roles),
                required_staff_count=int(staff_count),
            )
            validate_rule_definition(str(key), rule)
            ORDER_RULES[str(key)] = rule


def _variant_details(spec: dict[str, Any]) -> list[dict[str, Any]]:
    variant_by_label = {
        detail_label: key
        for key, detail_label, _allowed_roles, _staff_count in spec["variants"]
    }
    return [
        {
            "label": "單陪（不限）",
            "value": "single_any",
            "rule_key": str(spec["base_single"]),
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
        {
            "label": "女單陪",
            "value": "female_single",
            "rule_key": variant_by_label["女單陪"],
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
        {
            "label": "男單陪",
            "value": "male_single",
            "rule_key": variant_by_label["男單陪"],
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
        {
            "label": "雙陪（不限）",
            "value": "double_any",
            "rule_key": str(spec["base_double"]),
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
        {
            "label": "女雙陪",
            "value": "female_double",
            "rule_key": variant_by_label["女雙陪"],
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
        {
            "label": "男雙陪",
            "value": "male_double",
            "rule_key": variant_by_label["男雙陪"],
            "quantity_unit": "小時",
            "min_quantity": 1,
            "max_quantity": 24,
        },
    ]


def _patch_catalog() -> None:
    from services import orders

    for spec in _VARIANT_SPECS:
        base_keys = {str(spec["base_single"]), str(spec["base_double"])}
        replacement = _variant_details(spec)

        for groups in orders.SELF_SERVICE_ORDER_CATALOG.values():
            for group in groups:
                details = list(group.get("details", []))
                detail_keys = {
                    str(detail.get("rule_key") or "")
                    for detail in details
                }
                if not base_keys.issubset(detail_keys):
                    continue

                first_index = min(
                    index
                    for index, detail in enumerate(details)
                    if str(detail.get("rule_key") or "") in base_keys
                )
                remaining = [
                    dict(detail)
                    for detail in details
                    if str(detail.get("rule_key") or "") not in base_keys
                ]
                group["details"] = (
                    remaining[:first_index]
                    + [dict(item) for item in replacement]
                    + remaining[first_index:]
                )


def _patch_loyalty_scope_aliases() -> None:
    from services import loyalty_benefits as loyalty

    aliases = getattr(loyalty, "_LOYALTY_SCOPE_FAMILY_ALIASES", None)
    if not isinstance(aliases, dict):
        return

    for spec in _VARIANT_SPECS:
        family = str(spec["family"])
        aliases[str(spec["base_single"])] = family
        aliases[str(spec["base_double"])] = family
        for key, _label, _roles, _count in spec["variants"]:
            aliases[str(key)] = family


def _replace_point_catalog() -> None:
    from services import point_benefit_catalog as catalog

    if getattr(catalog, "_seat_split_20261028_installed", False):
        return

    active_non_service = [
        dict(item)
        for item in catalog.POINT_REDEEM_ITEMS
        if str(item.get("key") or "") not in _RETIRED_CURRENT_SERVICE_KEYS
    ]

    for old_key in _RETIRED_CURRENT_SERVICE_KEYS:
        old_item = catalog.POINT_REDEEM_ITEMS_BY_KEY.get(old_key)
        old_spec = catalog.POINT_BENEFIT_SPECS.get(old_key)
        if old_item is not None and old_key not in catalog.LEGACY_POINT_REDEEM_ITEMS_BY_KEY:
            legacy_item = dict(old_item)
            catalog.LEGACY_POINT_REDEEM_ITEMS.append(legacy_item)
            catalog.LEGACY_POINT_REDEEM_ITEMS_BY_KEY[old_key] = legacy_item
        if old_spec is not None:
            catalog.LEGACY_POINT_BENEFIT_SPECS[old_key] = dict(old_spec)

    catalog.POINT_REDEEM_ITEMS[:] = active_non_service + [
        dict(item) for item in _NEW_POINT_ITEMS
    ]
    catalog.POINT_REDEEM_ITEMS_BY_KEY.clear()
    catalog.POINT_REDEEM_ITEMS_BY_KEY.update({
        str(item["key"]): dict(item)
        for item in catalog.POINT_REDEEM_ITEMS
    })

    for old_key in _RETIRED_CURRENT_SERVICE_KEYS:
        catalog.POINT_BENEFIT_SPECS.pop(old_key, None)
    catalog.POINT_BENEFIT_SPECS.update({
        key: dict(value)
        for key, value in _NEW_POINT_SPECS.items()
    })

    catalog.ALL_POINT_BENEFIT_SPECS.clear()
    catalog.ALL_POINT_BENEFIT_SPECS.update({
        **catalog.LEGACY_POINT_BENEFIT_SPECS,
        **catalog.POINT_BENEFIT_SPECS,
    })

    original_tier = catalog.get_rule_service_tier

    def _service_seat_count(rule, player_count: Any = None) -> int | None:
        required = getattr(rule, "required_staff_count", 1)
        if str(required) == "player_count":
            if player_count in (None, ""):
                return None
            try:
                return max(1, int(player_count or 1))
            except (TypeError, ValueError):
                return 1
        try:
            return max(1, int(required or 1))
        except (TypeError, ValueError):
            return 1

    def is_service_bonus_allowed_for_rule(
        rule,
        benefit: dict[str, Any] | None,
        player_count: Any = None,
    ) -> bool:
        benefit_value = dict(benefit or {})
        if str(benefit_value.get("kind") or "") != "service_bonus":
            return True

        expected_tier = str(benefit_value.get("service_tier") or "").strip().lower()
        if not expected_tier or expected_tier != original_tier(rule):
            return False

        try:
            expected_seats = int(benefit_value.get("seat_count") or 0)
        except (TypeError, ValueError):
            expected_seats = 0
        if expected_seats <= 0:
            return True

        actual_seats = _service_seat_count(rule, player_count)
        if actual_seats is None:
            # The generic policy probe can run before a player-count product has
            # supplied its selected seat count. The final checkout check below
            # re-runs this with the concrete selection.
            return True
        return int(actual_seats) == int(expected_seats)

    def adapt_point_benefit_for_rule(
        rule,
        benefit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        adapted = dict(benefit or {})
        if str(adapted.get("kind") or "") != "service_bonus":
            return adapted

        pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()
        bonus_size = str(adapted.get("bonus_size") or "").strip().lower()
        tier = str(adapted.get("service_tier") or "").strip().lower()
        try:
            seat_count = max(1, int(adapted.get("seat_count") or 1))
        except (TypeError, ValueError):
            seat_count = 1

        tier_text = "娛樂" if tier == "entertainment" else "技術"
        seat_text = "單陪" if seat_count == 1 else "雙陪" if seat_count == 2 else f"{seat_count}陪"
        benefit_text = f"{tier_text}{seat_text}"

        if pricing_type == "hourly":
            hours = 0.5 if bonus_size == "small" else 1.0
            unit_text = "30 分鐘" if abs(hours - 0.5) < 0.001 else "1 小時"
            adapted["kind"] = "extra_hours"
            adapted["hours"] = hours
            adapted["pricing_types"] = ("hourly",)
            adapted["name"] = f"{benefit_text}加贈｜{unit_text}"
            adapted["summary"] = (
                f"服務時間 +{unit_text}，{seat_count} 位陪玩同步加贈；"
                "店內吸收額外服務成本"
            )
        elif pricing_type == "game":
            games = 1 if bonus_size == "small" else 2
            adapted["kind"] = "extra_games"
            adapted["games"] = games
            adapted["pricing_types"] = ("game",)
            adapted["name"] = f"{benefit_text}加贈｜{games} 局"
            adapted["summary"] = (
                f"服務局數 +{games} 局，{seat_count} 位陪玩同步加贈；"
                "店內吸收額外服務成本"
            )

        return adapted

    catalog.is_service_bonus_allowed_for_rule = is_service_bonus_allowed_for_rule
    catalog.adapt_point_benefit_for_rule = adapt_point_benefit_for_rule
    catalog._seat_split_20261028_service_seat_count = _service_seat_count
    catalog._seat_split_20261028_installed = True

    from services import self_service_point_benefit_policy as point_policy

    original_check = point_policy.check_order_point_benefit_allowed

    def check_order_point_benefit_allowed(rule, benefit, data: dict | None = None):
        allowed, reason = original_check(rule, benefit, data)
        if not allowed:
            return allowed, reason

        spec = dict(benefit or {})
        if str(spec.get("kind") or "") != "service_bonus":
            return allowed, reason

        payload = data or {}
        if not is_service_bonus_allowed_for_rule(
            rule,
            spec,
            player_count=payload.get("player_count"),
        ):
            return False, "這張服務加贈券不適用此單陪／雙陪規格。"
        return True, ""

    point_policy.check_order_point_benefit_allowed = check_order_point_benefit_allowed


def install_entertainment_companion_policy_20261028() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_gendered_rules()
    _patch_catalog()
    _patch_loyalty_scope_aliases()
    _replace_point_catalog()
    _INSTALLED = True


def install_point_service_financial_runtime_20261028() -> None:
    """Make double-companion point rewards pay both seats while preserving legacy keys."""
    global _FINANCIAL_RUNTIME_INSTALLED
    if _FINANCIAL_RUNTIME_INSTALLED:
        return

    from services import point_benefit_catalog as catalog
    from services import self_service_financials as financials

    if hasattr(financials, "_seat_split_20261028_original_calculate"):
        _FINANCIAL_RUNTIME_INSTALLED = True
        return

    original = financials.calculate_self_service_financials
    financials._seat_split_20261028_original_calculate = original

    def calculate_self_service_financials(rule, price_result, data: dict):
        result = original(rule, price_result, data)
        key = str(result.get("point_benefit_key") or "").strip()
        benefit = catalog.get_point_benefit_item(key)
        if not benefit:
            return result

        try:
            funded_seats = max(1, int(benefit.get("seat_count") or 1))
        except (TypeError, ValueError):
            funded_seats = 1
        if funded_seats <= 1:
            return result

        actual_seats = catalog.resolve_rule_staff_count(
            rule,
            (data or {}).get("player_count", 1),
        )
        funded_seats = min(funded_seats, max(1, int(actual_seats or 1)))
        if funded_seats <= 1:
            return result

        one_seat_value = max(0, int(result.get("point_service_value") or 0))
        if one_seat_value > 0:
            additional = one_seat_value * (funded_seats - 1)
            result["point_service_value"] = one_seat_value + additional
            result["payout_base_amount"] = max(
                0,
                int(result.get("payout_base_amount") or 0) + additional,
            )
            result["store_absorbed_amount"] = max(
                0,
                int(result.get("store_absorbed_amount") or 0) + additional,
            )

        bonus_text = str(result.get("service_bonus_text") or "")
        if bonus_text:
            result["service_bonus_text"] = bonus_text.replace(
                "（1 位陪玩）",
                f"（{funded_seats} 位陪玩同步加贈）",
            )
        return result

    financials.calculate_self_service_financials = calculate_self_service_financials
    _FINANCIAL_RUNTIME_INSTALLED = True


__all__ = [
    "install_entertainment_companion_policy_20261028",
    "install_point_service_financial_runtime_20261028",
]
