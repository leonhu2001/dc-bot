from __future__ import annotations

from typing import Any, Callable

from services.point_benefit_catalog import (
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)
from services.unified_service_point_policy import (
    calculate_rule_price_service_point_cost,
    is_current_service_bonus,
    is_rule_service_bonus_supported,
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


def get_pending_point_benefit_info(
    data: dict,
    *,
    point_item_lookup: Callable[[str], Any],
    to_int: Callable[..., int],
) -> dict | None:
    """Return point charge due at payment from the authoritative formal rule."""
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

    # Current seat-aware service rewards must always resolve a formal product and
    # must be explicitly service-extendable. This is the payment-time backstop for
    # clients that try to bypass Discord/Web option filtering.
    if is_current_service_bonus(item):
        if rule is None:
            raise ValueError("找不到正式商品規則，無法安全計算點數成本；請重新選擇商品後再付款。")
        if not is_rule_service_bonus_supported(rule):
            raise ValueError("此正式商品不支援加時／加局，不能使用服務加贈點數福利。")
        if not is_service_bonus_allowed_for_rule(
            rule,
            item,
            player_count=data.get("player_count"),
        ):
            raise ValueError("這張點數加時／加局福利與目前陪玩人數或商品類型不一致，請重新選擇。")

        cost = calculate_rule_price_service_point_cost(
            rule=rule,
            benefit=item,
            player_count=data.get("player_count"),
        )
        adapted = adapt_point_benefit_for_rule(rule, item)
        name = str(adapted.get("name") or item.get("name") or benefit_key)
        if cost <= 0:
            raise ValueError("無法依正式商品規則重新計算點數成本，請重新選擇點數福利。")

        # Snapshot is output-only for current service products; payment never trusts it.
        data["point_benefit_cost"] = int(cost)
        data["point_benefit_name"] = name
        return {"key": benefit_key, "name": name, "cost": int(cost)}

    # Historical non-seat-aware service aliases and non-service point products keep
    # their stored snapshot behavior so this deployment does not rewrite old orders.
    name = str(data.get("point_benefit_name") or item.get("name") or benefit_key)
    cost = to_int(
        data.get("point_benefit_cost"),
        to_int(item.get("cost"), 0) if item else 0,
    ) or 0
    if cost <= 0:
        return None
    return {"key": benefit_key, "name": name, "cost": int(cost)}
