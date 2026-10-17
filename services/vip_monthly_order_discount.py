from __future__ import annotations

from typing import Any, Callable


VIP_MONTHLY_CASH_MINIMUM_ORDER_AMOUNT: dict[str, int] = {
    "monthly_coupon_200": 1500,
    "monthly_coupon_500": 4000,
}


def get_vip_monthly_cash_minimum_order_amount(benefit_key: str | None) -> int:
    return int(
        VIP_MONTHLY_CASH_MINIMUM_ORDER_AMOUNT.get(
            str(benefit_key or "").strip(),
            0,
        )
    )


def resolve_vip_monthly_cash_discount(
    data: dict[str, Any],
    *,
    has_point_benefit: bool,
    max_discount_amount: int,
    original_service_amount: int | None = None,
) -> tuple[dict[str, Any] | None, int]:
    """Resolve and revalidate a selected VIP monthly cash voucher.

    The usage threshold is based on the original service amount before VIP or
    coupon discounts.  Revalidation runs every time financials are rebuilt, so
    an edited order that falls below the threshold can no longer keep the
    voucher applied.
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

    benefit_key = str(selected.get("benefit_key") or "").strip()
    minimum_order = get_vip_monthly_cash_minimum_order_amount(benefit_key)

    if original_service_amount is None:
        for key in ("service_original_amount", "original_amount", "manual_staff_amount"):
            raw = data.get(key)
            if raw not in (None, ""):
                try:
                    original_service_amount = int(float(raw))
                    break
                except (TypeError, ValueError):
                    continue

    if minimum_order > 0:
        if original_service_amount is None:
            raise ValueError("無法確認訂單原始服務金額，請重新試算後再使用 VIP 月券。")
        original_service_amount = max(0, int(original_service_amount or 0))
        if original_service_amount < minimum_order:
            amount_label = int(selected.get("amount") or 0)
            raise ValueError(
                f"{amount_label}T VIP 月券需單筆原始服務金額滿 {minimum_order:,}T 才能使用。"
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
