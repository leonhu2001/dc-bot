from __future__ import annotations

"""Public web checkout service.

The large checkout implementation lives in checkout_preview_core. Point-benefit
policy is kept here because it is shared with Discord and is expected to evolve
independently from the rest of checkout previewing.
"""

from typing import Any

from services.point_benefit_catalog import (
    LEGACY_POINT_REDEEM_ITEMS,
    POINT_REDEEM_ITEMS,
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)
from web.app.services import checkout_preview_core as _core


# Re-export the existing checkout surface without duplicating the mature checkout
# implementation. Dunder names stay private; point-policy symbols below replace
# the corresponding core symbols intentionally.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


_CORE_CALCULATE_CHECKOUT_FINANCIALS = _core.calculate_checkout_financials


def _materialize_point_item(key: str) -> dict | None:
    item = get_point_benefit_item(key)
    return dict(item) if item is not None else None


POINT_ITEMS = [
    item
    for item in (
        _materialize_point_item(str(source.get("key") or ""))
        for source in POINT_REDEEM_ITEMS
    )
    if item is not None
]


# Legacy benefits are lookup-only so an order started before the migration can
# still preview/finish, but they are never returned by list_point_options().
POINT_ITEM_MAP = {
    item["key"]: item
    for item in [
        *POINT_ITEMS,
        *[
            benefit
            for benefit in (
                _materialize_point_item(str(source.get("key") or ""))
                for source in LEGACY_POINT_REDEEM_ITEMS
            )
            if benefit is not None
        ],
    ]
}


def _point_item_for_rule(rule, item: dict) -> dict:
    return adapt_point_benefit_for_rule(rule, item)


def point_item_status(
    *,
    rule_key: str,
    point_item_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool,
) -> dict:
    rule = ORDER_RULES.get(str(rule_key))
    item = POINT_ITEM_MAP.get(str(point_item_key))

    if rule is None or item is None:
        return {"allowed": False, "reason": "不支援這個點數福利。"}

    if point_balance < int(item["cost"]):
        return {"allowed": False, "reason": "點數不足。"}

    if not bool(rule.point_benefits_allowed):
        return {"allowed": False, "reason": "此方案不可使用點數福利。"}

    category = str(rule.category)
    if category == "steam":
        return {"allowed": False, "reason": "Steam遊戲目前不可使用點數福利。"}

    if category in {"fun", "delta_desktop_fun", "title"}:
        return {"allowed": False, "reason": "趣味單不可使用點數福利。"}

    if str(rule_key).startswith("basic_trial_"):
        return {"allowed": False, "reason": "體驗單不可使用點數福利。"}

    pricing_type = str(rule.pricing_type)
    kind = str(item.get("kind") or "")

    if kind == "service_bonus":
        if pricing_type not in {"hourly", "game"}:
            return {"allowed": False, "reason": "服務加贈只適用計時或計局方案。"}
        if not is_service_bonus_allowed_for_rule(rule, item):
            return {"allowed": False, "reason": "這張服務加贈券不適用此陪玩類型。"}

    pricing_types = tuple(item.get("pricing_types") or ())
    if pricing_types and pricing_type not in pricing_types:
        label = "計時" if "hourly" in pricing_types else "計局"
        return {"allowed": False, "reason": f"此點數福利只適用{label}方案。"}

    if kind == "free_specify_fee":
        if not rule.allow_specify:
            return {"allowed": False, "reason": "此方案不開放指定。"}
        if pricing_type == "hourly" and int(quantity) >= 2:
            return {"allowed": False, "reason": "2 小時以上本來就免指定費。"}
        if not has_specified_staff:
            return {
                "allowed": False,
                "requires_specified": True,
                "reason": "需先指定人員。",
            }

    if kind == "extra_hours" and pricing_type != "hourly":
        return {"allowed": False, "reason": "加時只適用計時方案。"}

    if kind == "extra_games" and pricing_type != "game":
        return {"allowed": False, "reason": "加局只適用計局方案。"}

    return {"allowed": True, "reason": ""}


def list_point_options(
    *,
    rule_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool = False,
) -> list[dict]:
    rule = ORDER_RULES.get(str(rule_key))
    if rule is None:
        return []

    result = []
    for item in POINT_ITEMS:
        status = point_item_status(
            rule_key=rule_key,
            point_item_key=item["key"],
            point_balance=point_balance,
            quantity=quantity,
            has_specified_staff=has_specified_staff,
        )
        data = _point_item_for_rule(rule, item)
        data.update(status)
        result.append(data)

    return result


def calculate_point_service_value(
    *,
    quote: dict,
    vip_pay_rate: int,
    point_item: dict | None,
) -> int:
    """Return the store-funded value for one companion seat only."""
    if not point_item:
        return 0

    kind = str(point_item.get("kind") or "")
    if kind == "extra_hours":
        units = float(point_item.get("hours") or 0)
    elif kind == "extra_games":
        units = float(point_item.get("games") or 0)
    else:
        return 0

    if units <= 0:
        return 0

    quantity = max(1, int(quote.get("quantity") or 1))
    staff_count = max(1, int(quote.get("required_staff_count") or 1))
    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))
    gross_extra_value = int(round((service_amount / quantity / staff_count) * units))

    # VIP only changes the customer's charge; the extra service is funded at its
    # normal one-seat value so the selected companion's payout is not reduced.
    return max(0, gross_extra_value)


def calculate_checkout_financials(
    *,
    service_amount: int,
    vip_pay_rate: int,
    specify_fee: int,
    point_item: dict | None,
    wallet_balance: int,
    use_wallet: bool,
    point_service_value: int = 0,
    benefit_coupon: dict | None = None,
    benefit_service_value: int = 0,
) -> dict:
    result = _CORE_CALCULATE_CHECKOUT_FINANCIALS(
        service_amount=service_amount,
        vip_pay_rate=vip_pay_rate,
        specify_fee=specify_fee,
        point_item=point_item,
        wallet_balance=wallet_balance,
        use_wallet=use_wallet,
        point_service_value=point_service_value,
        benefit_coupon=benefit_coupon,
        benefit_service_value=benefit_service_value,
    )

    if point_item and str(point_item.get("kind") or "") in {"extra_hours", "extra_games"}:
        note = str(result.get("point_service_note") or "").strip()
        if note and "1 位陪玩" not in note:
            result["point_service_note"] = f"{note}（1 位陪玩）"

    return result


# Core checkout functions resolve these names from their own module globals.
# Point policy is injected once here so build_checkout_options/preview continue to
# use the same stable implementation while sharing the canonical policy source.
_core.POINT_ITEMS = POINT_ITEMS
_core.POINT_ITEM_MAP = POINT_ITEM_MAP
_core._point_item_for_rule = _point_item_for_rule
_core.point_item_status = point_item_status
_core.list_point_options = list_point_options
_core.calculate_point_service_value = calculate_point_service_value
_core.calculate_checkout_financials = calculate_checkout_financials
