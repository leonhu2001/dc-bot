from __future__ import annotations

from typing import Any, Callable


def parse_discount_percent_text(value: str | None) -> float:
    raw = str(value or "").strip().replace("%", "")

    if not raw:
        return 100.0

    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(
            "折後比例請輸入數字，例如 90 代表 9 折。"
        ) from exc

    if parsed < 0 or parsed > 100:
        raise ValueError(
            "折後比例只能輸入 0～100。"
        )

    return parsed


def parse_cash_amount_text(value: str | None) -> int:
    raw = str(value or "").strip().replace(",", "")

    if not raw:
        return 0

    try:
        amount = int(float(raw))
    except ValueError as exc:
        raise ValueError(
            "固定折扣金額請輸入數字，例如 100。"
        ) from exc

    if amount < 0:
        raise ValueError(
            "固定折扣金額不能小於 0。"
        )

    return amount


def resolve_manual_discount_rate_percent(data: dict) -> float:
    raw = data.get("manual_discount_percent")

    if raw is None or str(raw).strip() == "":
        return 100.0

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0

    value = max(
        0.0,
        min(100.0, value),
    )

    if (
        str(
            data.get("manual_discount_mode")
            or ""
        ).strip().lower()
        == "pay_rate"
    ):
        return value

    # legacy：舊資料 10 = 折掉 10%；新制等同折後 90%。
    return 100.0 - value


def calculate_manual_price_adjustment(
    base_amount: int,
    data: dict,
    *,
    to_int: Callable[..., int],
    allocate_store_absorbed_fixed_discount: Callable[..., Any],
) -> dict:
    original = max(0, int(base_amount or 0))
    rate = resolve_manual_discount_rate_percent(data)
    after_percent = max(
        0,
        min(original, int(round(original * rate / 100))),
    )
    percent_off = original - after_percent

    raw_fixed = data.get("fixed_discount_amount")
    if raw_fixed is None:
        raw_fixed = data.get("cash_coupon_amount")

    fixed = max(
        0,
        min(after_percent, to_int(raw_fixed, 0) or 0),
    )
    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
    )

    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "service_original_amount": original,
        "original_amount": original,
        "manual_discount_percent": rate,
        "discount_rate_percent": rate,
        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,
        "payout_base_amount": allocation.payout_base_amount,
        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,
        "store_absorbed_amount": allocation.store_absorbed_amount,
        "customer_pay_amount": allocation.customer_pay_amount,
        "manual_discount_reason": str(
            data.get("manual_discount_reason") or ""
        ).strip(),
        "cash_coupon_reason": str(
            data.get("cash_coupon_reason") or ""
        ).strip(),
    }


def apply_manual_price_adjustment_to_order_data(
    data: dict,
    base_amount: int,
    *,
    calculate_adjustment: Callable[[int, dict], dict],
    format_amount: Callable[[int | None], str],
) -> dict:
    adjustment = calculate_adjustment(base_amount, data)

    for key, value in adjustment.items():
        data[key] = value

    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = format_amount(adjustment["customer_pay_amount"])

    return adjustment
