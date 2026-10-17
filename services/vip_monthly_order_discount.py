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

    benefit_key = str(selected.get("benefit_key") or "")
    minimum = int(VIP_MONTHLY_CASH_ORDER_MINIMUMS.get(benefit_key, 0) or 0)
    original_amount = _original_service_amount(
        data,
        fallback_after_percent=max_discount_amount,
        explicit_amount=original_service_amount,
    )
    if minimum > 0 and original_amount < minimum:
        amount_label = int(selected.get("amount") or 0)
        raise ValueError(
            f"VIP {amount_label}T 月券需單筆原始服務金額滿 {minimum:,}T 才能使用。"
        )

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
