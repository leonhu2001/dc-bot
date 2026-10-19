from __future__ import annotations

from typing import Any, Callable

from services.point_benefit_catalog import (
    ALL_POINT_BENEFIT_SPECS,
    POINT_REDEEM_ITEMS_BY_KEY as CANONICAL_POINT_REDEEM_ITEMS_BY_KEY,
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)


ORDER_POINT_BENEFIT_SPECS: dict = dict(ALL_POINT_BENEFIT_SPECS)
POINT_REDEEM_ITEMS_BY_KEY: dict = dict(CANONICAL_POINT_REDEEM_ITEMS_BY_KEY)
_to_int: Callable[..., int]
get_current_reward_points: Callable[..., int]
get_customer_reward_data: Callable[..., Any]


def configure_self_service_point_benefits(
    *,
    order_point_benefit_specs: dict,
    point_redeem_items_by_key: dict,
    to_int: Callable[..., int],
    current_reward_points: Callable[..., int],
    customer_reward_data: Callable[..., Any],
) -> None:
    global ORDER_POINT_BENEFIT_SPECS
    global POINT_REDEEM_ITEMS_BY_KEY
    global _to_int
    global get_current_reward_points
    global get_customer_reward_data

    # Keep legacy caller data readable while canonical definitions win for
    # current checkout behavior.
    ORDER_POINT_BENEFIT_SPECS = {
        **dict(order_point_benefit_specs or {}),
        **ALL_POINT_BENEFIT_SPECS,
    }
    POINT_REDEEM_ITEMS_BY_KEY = {
        **dict(point_redeem_items_by_key or {}),
        **CANONICAL_POINT_REDEEM_ITEMS_BY_KEY,
    }
    _to_int = to_int
    get_current_reward_points = current_reward_points
    get_customer_reward_data = customer_reward_data


def get_order_point_item(key: str | None) -> dict | None:
    canonical = get_point_benefit_item(key)
    if canonical is not None:
        return canonical
    if not key:
        return None

    try:
        item = POINT_REDEEM_ITEMS_BY_KEY.get(str(key))
    except Exception:
        item = None
    if item is None:
        return None

    merged = dict(item)
    merged.update(ORDER_POINT_BENEFIT_SPECS.get(str(key)) or {})
    return merged


def get_customer_point_balance_for_order(customer_id: int) -> int:
    try:
        reward_data = get_customer_reward_data(int(customer_id))
        return int(get_current_reward_points(reward_data))
    except Exception:
        return 0


def is_order_point_benefit_allowed_for_rule(
    rule,
    key: str,
    data: dict | None = None,
) -> tuple[bool, str]:
    data = data or {}
    key = str(key or "")
    spec = dict(get_order_point_item(key) or {})
    if not spec:
        return False, "這個點數福利不支援新下單流程。"
    if not getattr(rule, "point_benefits_allowed", False):
        return False, "此分類不可使用點數福利。"

    category = str(getattr(rule, "category", "")).lower()
    rule_key = str(getattr(rule, "key", "") or "")
    rule_label = str(getattr(rule, "label", "") or "")
    if category == "steam":
        return False, "Steam遊戲目前不可使用點數福利。"
    if category in {"fun", "delta_desktop_fun", "title"}:
        return False, "趣味單 / 高難度稱號不可使用點數福利。"
    if rule_key.startswith("basic_trial_") or rule_label.startswith("體驗單"):
        return False, "體驗單不可使用點數福利。"

    kind = spec.get("kind")
    pricing_type = str(getattr(rule, "pricing_type", "") or "")
    if kind == "service_bonus":
        if pricing_type not in {"hourly", "game"}:
            return False, "服務加贈只適用計時或計局方案。"
        if not is_service_bonus_allowed_for_rule(rule, spec):
            return False, "這張服務加贈券不適用此陪玩類型。"

    if kind == "free_specify_fee":
        if not getattr(rule, "allow_specify", False):
            return False, "此項目不開放指定，因此不能使用免指定費。"
        if not data.get("specified_staff_ids"):
            return False, "請先指定人員，再使用免指定費。"
        if pricing_type == "hourly":
            quantity = _to_int(data.get("quantity"), 1) or 1
            if quantity >= 2:
                return False, "2 小時以上本來就免指定費，不需要再使用免指定費福利。"

    pricing_types = tuple(spec.get("pricing_types") or ())
    if pricing_types and pricing_type not in pricing_types:
        return False, "這個點數福利不適用此計價方式。"
    if kind == "extra_hours" and pricing_type != "hourly":
        return False, "加時只適用計時方案。"
    if kind == "extra_games" and pricing_type != "game":
        return False, "加局只適用計局方案。"
    return True, ""


def _adapt_order_point_benefit_for_rule(rule, benefit: dict) -> dict:
    return adapt_point_benefit_for_rule(rule, benefit)


def get_selected_order_point_benefit(data: dict, rule=None) -> dict | None:
    key = data.get("selected_point_benefit_key")
    item = get_order_point_item(key)
    if item is None:
        return None

    if rule is not None:
        allowed, _ = is_order_point_benefit_allowed_for_rule(rule, str(key), data)
        if not allowed:
            return None

    merged = dict(item)
    if rule is not None:
        merged = _adapt_order_point_benefit_for_rule(rule, merged)
    return merged
