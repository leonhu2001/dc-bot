from __future__ import annotations

from pathlib import Path
import re


PATH = Path("web/app/services/checkout_preview.py")


def sub_once(pattern: str, replacement: str, source: str) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected exactly one match, got {count}: {pattern[:80]!r}")
    return updated


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    point_items = '''POINT_ITEMS = [
    {
        "key": "discount_20",
        "cost": 10,
        "name": "20T 折價券",
        "kind": "cash_discount",
        "amount": 20,
    },
    {
        "key": "discount_30",
        "cost": 15,
        "name": "30T 折價券",
        "kind": "cash_discount",
        "amount": 30,
    },
    {
        "key": "free_specify_fee",
        "cost": 30,
        "name": "免指定費 1 次",
        "kind": "free_specify_fee",
    },
    {
        "key": "discount_100",
        "cost": 45,
        "name": "100T 折價券",
        "kind": "cash_discount",
        "amount": 100,
    },
    {
        "key": "extra_hour_30m",
        "cost": 60,
        "name": "加時 30 分鐘",
        "kind": "extra_hours",
        "hours": 0.5,
        "pricing_types": ("hourly",),
    },
    {
        "key": "extra_hour_1h",
        "cost": 110,
        "name": "加時 1 小時",
        "kind": "extra_hours",
        "hours": 1,
        "pricing_types": ("hourly",),
    },
    {
        "key": "extra_game_1",
        "cost": 40,
        "name": "加 1 局",
        "kind": "extra_games",
        "games": 1,
        "pricing_types": ("game",),
    },
    {
        "key": "extra_game_2",
        "cost": 70,
        "name": "加 2 局",
        "kind": "extra_games",
        "games": 2,
        "pricing_types": ("game",),
    },
]'''
    text = sub_once(
        r"POINT_ITEMS = \[.*?\n\]\n\n\nPOINT_ITEM_MAP = \{",
        point_items + "\n\n\nPOINT_ITEM_MAP = {",
        text,
    )

    point_rules = '''def _point_item_for_rule(rule, item: dict) -> dict:
    return dict(item or {})


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
    pricing_types = tuple(item.get("pricing_types") or ())
    if pricing_types and pricing_type not in pricing_types:
        label = "計時" if "hourly" in pricing_types else "計局"
        return {"allowed": False, "reason": f"此點數福利只適用{label}方案。"}

    kind = str(item["kind"])
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

    pricing_type = str(rule.pricing_type)
    result = []
    for item in POINT_ITEMS:
        pricing_types = tuple(item.get("pricing_types") or ())
        if pricing_types and pricing_type not in pricing_types:
            continue

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

    return result'''
    text = sub_once(
        r"def _point_item_for_rule\(rule, item: dict\) -> dict:.*?\n\n# ============================================================\n# Financial calculation",
        point_rules + "\n\n\n# ============================================================\n# Financial calculation",
        text,
    )

    financials = '''def calculate_point_service_value(
    *,
    quote: dict,
    vip_pay_rate: int,
    point_item: dict | None,
) -> int:
    """Compute store-funded payout value for point-added time or games."""
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
    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))
    gross_extra_value = int(round((service_amount / quantity) * units))
    rate = max(0, min(100, int(vip_pay_rate or 100)))
    return max(0, int(round(gross_extra_value * rate / 100)))


def calculate_checkout_financials(
    *,
    service_amount: int,
    vip_pay_rate: int,
    specify_fee: int,
    point_item: dict | None,
    wallet_balance: int,
    use_wallet: bool,
    point_service_value: int = 0,
) -> dict:
    service_amount = max(0, int(service_amount or 0))
    vip_pay_rate = max(0, min(100, int(vip_pay_rate or 100)))
    specify_fee = max(0, int(specify_fee or 0))
    wallet_balance = max(0, int(wallet_balance or 0))
    point_service_value = max(0, int(point_service_value or 0))

    after_vip = int(round(service_amount * vip_pay_rate / 100))
    vip_discount_amount = max(0, service_amount - after_vip)

    point_cash_discount = 0
    point_waived_specify = 0
    point_service_note = ""

    if point_item:
        kind = str(point_item.get("kind") or "")
        if kind == "cash_discount":
            point_cash_discount = min(
                after_vip,
                max(0, int(point_item.get("amount") or 0)),
            )
        elif kind == "free_specify_fee":
            point_waived_specify = specify_fee
        elif kind == "extra_hours":
            hours = float(point_item.get("hours") or 0)
            point_service_note = (
                "服務時間 +30 分鐘"
                if hours == 0.5
                else f"服務時間 +{hours:g} 小時"
            )
        elif kind == "extra_games":
            games = int(point_item.get("games") or 0)
            point_service_note = f"服務局數 +{games} 局"

    effective_specify_fee = max(0, specify_fee - point_waived_specify)
    after_point = max(0, after_vip - point_cash_discount)
    subtotal = max(0, after_point + effective_specify_fee)
    wallet_use = min(wallet_balance, subtotal) if use_wallet else 0
    remaining = max(0, subtotal - wallet_use)

    # All point rewards are funded by the store. Customer discounts and free
    # specify do not lower worker payout, while point-added time/games add the
    # equivalent discounted service value to the payout base.
    payout_base = max(0, after_vip + specify_fee + point_service_value)
    point_store_absorbed = max(
        0,
        point_cash_discount + point_waived_specify + point_service_value,
    )

    return {
        "service_amount": service_amount,
        "original_amount": service_amount,
        "vip_pay_rate": vip_pay_rate,
        "manual_discount_percent": vip_pay_rate,
        "discount_rate_percent": vip_pay_rate,
        "vip_discount_amount": vip_discount_amount,
        "manual_discount_amount": vip_discount_amount,
        "percent_discount_amount": vip_discount_amount,
        "service_after_vip": after_vip,
        "specify_fee": specify_fee,
        "cash_coupon_amount": 0,
        "fixed_discount_amount": 0,
        "point_cash_discount": point_cash_discount,
        "point_discount_coupon_amount": point_cash_discount,
        "point_waived_specify_fee": point_waived_specify,
        "effective_specify_fee": effective_specify_fee,
        "point_service_note": point_service_note,
        "point_service_value": point_service_value,
        "point_store_absorbed_amount": point_store_absorbed,
        "subtotal_before_wallet": subtotal,
        "customer_pay_amount": subtotal,
        "wallet_use_amount": wallet_use,
        "remaining_pay_amount": remaining,
        "payout_base_amount": payout_base,
        "payout_base_preview": payout_base,
        "store_absorbed_amount": point_store_absorbed,
        "store_absorbed_preview": point_store_absorbed,
    }'''
    text = sub_once(
        r"def calculate_checkout_financials\(.*?\n\n# ============================================================\n# Checkout endpoints data",
        financials + "\n\n\n# ============================================================\n# Checkout endpoints data",
        text,
    )

    old = '''            point_item=\n                selected_point_item,\n\n            wallet_balance='''
    new = '''            point_item=\n                selected_point_item,\n\n            point_service_value=\n                calculate_point_service_value(\n                    quote=quote,\n                    vip_pay_rate=vip_rate,\n                    point_item=selected_point_item,\n                ),\n\n            wallet_balance='''
    if old not in text:
        raise SystemExit("checkout financial call insertion point not found")
    text = text.replace(old, new, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
