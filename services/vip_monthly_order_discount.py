from __future__ import annotations

from typing import Any, Callable


VIP_MONTHLY_CASH_ORDER_MINIMUMS: dict[str, int] = {
    "monthly_coupon_200": 1500,
    "monthly_coupon_500": 4000,
}


def _original_service_amount(
    data: dict[str, Any],
    *,
    fallback_after_percent: int,
    explicit_amount: int | None = None,
) -> int:
    if explicit_amount is not None:
        return max(0, int(explicit_amount or 0))

    # Self-service finance writes service_original_amount on every refresh. That
    # value is deliberately before VIP percentage and before any cash coupon.
    for key in (
        "service_original_amount",
        "original_service_amount",
        "service_amount_before_discount",
    ):
        value = data.get(key)
        if value not in (None, ""):
            try:
                return max(0, int(round(float(value))))
            except (TypeError, ValueError):
                pass

    # Compatibility fallback for a draft that predates the new field. Reverse
    # the stored percentage when possible so a valid 1,500 / 4,000 order is not
    # rejected merely because a 98/96/94% VIP rate has already been applied.
    after_percent = max(0, int(fallback_after_percent or 0))
    for key in (
        "manual_discount_percent",
        "discount_rate_percent",
        "vip_pay_rate",
    ):
        try:
            rate = float(data.get(key) or 0)
        except (TypeError, ValueError):
            rate = 0
        if 0 < rate <= 100:
            return max(after_percent, int(round(after_percent * 100 / rate)))

    return after_percent


def get_vip_monthly_cash_order_status(
    selected: dict[str, Any] | None,
    *,
    original_service_amount: int,
) -> dict[str, Any]:
    """Return the canonical current-order eligibility status for a VIP cash voucher."""
    selected = dict(selected or {})
    benefit_key = str(selected.get("benefit_key") or "")
    amount = max(0, int(selected.get("amount") or 0))
    minimum = max(0, int(VIP_MONTHLY_CASH_ORDER_MINIMUMS.get(benefit_key, 0) or 0))
    current = max(0, int(original_service_amount or 0))
    shortfall = max(0, minimum - current)
    return {
        "benefit_key": benefit_key,
        "title": str(selected.get("title") or "VIP 每月折現券").strip() or "VIP 每月折現券",
        "amount": amount,
        "minimum": minimum,
        "current": current,
        "shortfall": shortfall,
        "eligible": minimum <= 0 or current >= minimum,
    }


def format_vip_monthly_cash_order_requirement(status: dict[str, Any]) -> str:
    title = str(status.get("title") or "VIP 每月折現券")
    minimum = max(0, int(status.get("minimum") or 0))
    current = max(0, int(status.get("current") or 0))
    shortfall = max(0, int(status.get("shortfall") or 0))
    eligible = bool(status.get("eligible"))

    if minimum <= 0:
        return f"{title}：目前可使用。"
    if eligible:
        return (
            f"{title}：低消 {minimum:,}T（以原始服務金額判定）；"
            f"目前 {current:,}T，可使用。"
        )
    return (
        f"{title}：低消 {minimum:,}T（以原始服務金額判定）；"
        f"目前 {current:,}T，尚差 {shortfall:,}T。"
    )


def resolve_vip_monthly_cash_discount(
    data: dict[str, Any],
    *,
    has_point_benefit: bool,
    max_discount_amount: int,
    original_service_amount: int | None = None,
) -> tuple[dict[str, Any] | None, int]:
    """Resolve and revalidate a selected VIP monthly cash voucher.

    VIP monthly coupons are now issued by tier without a trailing-spend gate.
    Usage is guarded on the current order's original service amount:
    200T => 1,500T; 500T => 4,000T.
    """
    selected_id = data.get("selected_vip_monthly_benefit_id")
    if selected_id in (None, ""):
        return None, 0

    if has_point_benefit:
        raise ValueError("VIP 每月福利券與點數福利同張訂單只能擇一使用。")

    customer_id = data.get("customer_id")
    if not customer_id:
        raise ValueError("無法確認 VIP 每月福利券的會員身分，請重新開啟福利選單。")

    from services.vip_monthly_benefits import get_available_cash_benefit

    selected = get_available_cash_benefit(selected_id, customer_id=customer_id)
    if selected is None:
        raise ValueError("這張 VIP 每月折現券已使用、已保留或已失效。")

    original_amount = _original_service_amount(
        data,
        fallback_after_percent=max_discount_amount,
        explicit_amount=original_service_amount,
    )
    status = get_vip_monthly_cash_order_status(
        selected,
        original_service_amount=original_amount,
    )
    if not status["eligible"]:
        raise ValueError(format_vip_monthly_cash_order_requirement(status))

    amount = max(
        0,
        min(
            int(selected.get("amount") or 0),
            max(0, int(max_discount_amount or 0)),
        ),
    )
    return selected, amount


def build_vip_monthly_discount_note(
    selected: dict[str, Any] | None,
    amount: int,
    *,
    formatter: Callable[[int], str],
) -> str | None:
    if not selected or int(amount or 0) <= 0:
        return None
    title = str(selected.get("title") or "VIP 每月折現券")
    return f"{title} -{formatter(int(amount))}"


def build_vip_monthly_discount_result(
    selected: dict[str, Any] | None,
    amount: int,
) -> dict[str, Any]:
    return {
        "vip_monthly_benefit_id": int(selected["id"]) if selected else None,
        "vip_monthly_benefit_key": str(selected.get("benefit_key") or "") if selected else "",
        "vip_monthly_benefit_title": str(selected.get("title") or "") if selected else "",
        "vip_monthly_cash_amount": int(amount or 0),
    }
