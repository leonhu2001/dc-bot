"""Shared SQL expressions for both ordinary-order and independent profile tips.

A profile chicken-leg has no web order. Its payment confirmation timestamp is
the earning date; never fabricate an order to make it appear in salary reports.
"""


def tip_earning_date_expr(tip: str = "p", order: str = "w") -> str:
    return (
        f"CASE WHEN {tip}.order_id IS NULL "
        f"THEN COALESCE(NULLIF({tip}.paid_at,''), NULLIF({tip}.created_at,'')) "
        f"ELSE COALESCE(NULLIF({order}.closed_at,''), "
        f"NULLIF({order}.updated_at,''), NULLIF({order}.created_at,'')) END"
    )


def tip_month_filter(month: str | None, *, tip: str = "p", order: str = "w"):
    if not str(month or "").strip():
        return "", []
    return f" AND substr({tip_earning_date_expr(tip, order)}, 1, 7) = ?", [str(month).strip()]


def tip_salary_order_scope(order_filter: str, month: str | None):
    """WHERE expression in UPDATE worker_tips (no aliases on target table)."""
    local_month = str(month or "").strip()
    extra = (
        " AND substr(COALESCE(NULLIF(paid_at,''),NULLIF(created_at,'')),1,7)=?"
        if local_month else ""
    )
    return (
        f"(order_id IN (SELECT w.id FROM web_orders w WHERE {order_filter}) "
        f"OR (order_id IS NULL{extra}))",
        [local_month] if local_month else [],
    )
