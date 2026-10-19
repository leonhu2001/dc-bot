from __future__ import annotations

from typing import Any, Callable

from services.point_benefit_catalog import (
    ALL_POINT_BENEFIT_SPECS,
    POINT_REDEEM_ITEMS_BY_KEY as CANONICAL_POINT_REDEEM_ITEMS_BY_KEY,
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
)
from services.self_service_point_benefit_policy import (
    check_order_point_benefit_allowed,
)


ORDER_POINT_BENEFIT_SPECS: dict = dict(ALL_POINT_BENEFIT_SPECS)
POINT_REDEEM_ITEMS_BY_KEY: dict = dict(CANONICAL_POINT_REDEEM_ITEMS_BY_KEY)
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
    global get_current_reward_points
    global get_customer_reward_data

    # Keep legacy caller data readable while canonical definitions win for
    # current checkout behavior. to_int remains accepted for runtime API
    # compatibility, but eligibility parsing is now pure and module-owned.
    del to_int
    ORDER_POINT_BENEFIT_SPECS = {
        **dict(order_point_benefit_specs or {}),
        **ALL_POINT_BENEFIT_SPECS,
    }
    POINT_REDEEM_ITEMS_BY_KEY = {
        **dict(point_redeem_items_by_key or {}),
        **CANONICAL_POINT_REDEEM_ITEMS_BY_KEY,
    }
    get_current_reward_points = current_reward_points
    get_customer_reward_data = customer_reward_data


def get_order_point_item(key: str | None) -> dict | None:
    canonical = get_point_benefit_item(key)
    if canonical is not None:
        return canonical
    if not key:
        return None

    item = POINT_REDEEM_ITEMS_BY_KEY.get(str(key))
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
    return check_order_point_benefit_allowed(
        rule,
        get_order_point_item(str(key or "")),
        data,
    )


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
