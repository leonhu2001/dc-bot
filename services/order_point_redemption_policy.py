from __future__ import annotations

from typing import Any, Callable

from services.point_benefit_catalog import (
    adapt_point_benefit_for_rule,
    calculate_service_bonus_point_cost,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
    uses_dynamic_service_point_cost,
)


def _resolve_order_rule(data: dict):
    """Resolve the authoritative rule without trusting stored money fields."""
    try:
        from services.order_rules import ORDER_RULES, get_rule
        from services.orders import ORDER_RULE_KEY_BY_LABEL
    except Exception:
        return None

    rule_key = str(data.get("order_rule_key") or "").strip()
    if rule_key:
        try:
            return get_rule(rule_key)
        except Exception:
            pass

    item_text = str(data.get("item") or "").strip()
    alias_key = ORDER_RULE_KEY_BY_LABEL.get(item_text)
    if alias_key:
        try:
            rule = get_rule(alias_key)
            data["order_rule_key"] = rule.key
            return rule
        except Exception:
            pass

    for rule in ORDER_RULES.values():
        if str(getattr(rule, "label", "") or "") == item_text:
            data["order_rule_key"] = rule.key
            return rule
    return None


def _is_dynamic_game_rule_hint(data: dict) -> bool:
    key = str(data.get("order_rule_key") or "").strip().lower()
    return key.startswith(("lol_", "valorant_", "apex_"))


def get_pending_point_benefit_info(
    data: dict,
    *,
    point_item_lookup: Callable[[str], Any],
    to_int: Callable[..., int],
) -> dict | None:
    """Return the point charge due at payment, recalculating dynamic games live."""
    if data.get("website_finance_settled"):
        return None

    benefit_key = str(
        data.get("point_benefit_key")
        or data.get("selected_point_benefit_key")
        or ""
    ).strip()
    if not benefit_key:
        return None

    injected_item = point_item_lookup(benefit_key)
    item = get_point_benefit_item(benefit_key) or injected_item or {}
    rule = _resolve_order_rule(data)

    if rule is not None and uses_dynamic_service_point_cost(rule, item):
        if not is_service_bonus_allowed_for_rule(
            rule,
            item,
            player_count=data.get("player_count"),
        ):
            raise ValueError("這張點數加時／加局福利與目前陪玩人數或商品類型不一致，請重新選擇。")

        cost = calculate_service_bonus_point_cost(
            rule=rule,
            benefit=item,
            player_count=data.get("player_count"),
        )
        adapted = adapt_point_benefit_for_rule(rule, item)
        name = str(adapted.get("name") or item.get("name") or benefit_key)
        if cost <= 0:
            raise ValueError("無法依正式商品規則重新計算點數成本，請重新選擇點數福利。")

        # Snapshot is output-only for dynamic products; payment never trusts it.
        data["point_benefit_cost"] = int(cost)
        data["point_benefit_name"] = name
        return {"key": benefit_key, "name": name, "cost": int(cost)}

    if (
        _is_dynamic_game_rule_hint(data)
        and str(item.get("kind") or "") == "service_bonus"
        and rule is None
    ):
        raise ValueError("找不到正式商品規則，無法安全計算點數成本；請重新選擇商品後再付款。")

    name = str(data.get("point_benefit_name") or item.get("name") or benefit_key)
    cost = to_int(
        data.get("point_benefit_cost"),
        to_int(item.get("cost"), 0) if item else 0,
    ) or 0
    if cost <= 0:
        return None
    return {"key": benefit_key, "name": name, "cost": int(cost)}
