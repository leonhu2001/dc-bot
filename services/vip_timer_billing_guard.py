from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text


_INSTALLED = False
VIP_TIMER_MINIMUM_SECONDS = 15 * 60


def calculate_total_with_minimum(order_id: int, db=None) -> tuple[int, int]:
    """Charge exact time after a whole-order 15 minute minimum.

    For a short order containing multiple rate segments, the minimum scales the
    actual mixed-rate amount proportionally to 15 minutes. This preserves the
    true weighted rate instead of arbitrarily charging the first or last mode.
    """
    from services import vip_timer as timer

    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT hourly_rate, billable_seconds "
                "FROM vip_timer_segments WHERE order_id=:order_id"
            ),
            {"order_id": int(order_id)},
        ).mappings().all()
        total_seconds = sum(
            max(0, int(row.get("billable_seconds") or 0))
            for row in rows
        )
        raw_amount = sum(
            Decimal(int(row.get("hourly_rate") or 0))
            * Decimal(max(0, int(row.get("billable_seconds") or 0)))
            / Decimal(3600)
            for row in rows
        )

        if 0 < total_seconds < VIP_TIMER_MINIMUM_SECONDS:
            raw_amount *= Decimal(VIP_TIMER_MINIMUM_SECONDS) / Decimal(total_seconds)

        rounded = int(raw_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return rounded, total_seconds
    finally:
        if owns:
            db.close()


def install_vip_timer_billing_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer as timer

    timer.calculate_total = calculate_total_with_minimum
    timer.VIP_TIMER_MINIMUM_SECONDS = VIP_TIMER_MINIMUM_SECONDS
    _INSTALLED = True


__all__ = [
    "VIP_TIMER_MINIMUM_SECONDS",
    "calculate_total_with_minimum",
    "install_vip_timer_billing_guard",
]
