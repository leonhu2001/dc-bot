from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text


_INSTALLED = False
VIP_TIMER_MINIMUM_SECONDS = 15 * 60


def calculate_total_with_minimum(order_id: int, db=None) -> tuple[int, int]:
    """Return final amount with a whole-order 15 minute minimum.

    Once actual billable time reaches 15 minutes, billing remains exact by
    second. For a shorter mixed-rate order, scale the actual mixed-rate amount
    proportionally to 15 minutes so no single segment is arbitrarily favored.
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
        amount = sum(
            Decimal(int(row.get("hourly_rate") or 0))
            * Decimal(max(0, int(row.get("billable_seconds") or 0)))
            / Decimal(3600)
            for row in rows
        )

        if 0 < total_seconds < VIP_TIMER_MINIMUM_SECONDS:
            amount *= Decimal(VIP_TIMER_MINIMUM_SECONDS) / Decimal(total_seconds)

        rounded = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return rounded, total_seconds
    finally:
        if owns:
            db.close()


def install_vip_timer_billing_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer as timer
    from services import vip_timer_runtime as runtime

    timer.calculate_total = calculate_total_with_minimum
    timer.VIP_TIMER_MINIMUM_SECONDS = VIP_TIMER_MINIMUM_SECONDS

    original_build_embed = runtime.build_vip_timer_embed

    def build_vip_timer_embed(order_id: int):
        embed = original_build_embed(int(order_id))
        embed.add_field(
            name="最低計費",
            value="整張單最低計費 15 分鐘；超過後依實際計時秒數換算。",
            inline=False,
        )
        return embed

    runtime.build_vip_timer_embed = build_vip_timer_embed
    _INSTALLED = True


__all__ = [
    "VIP_TIMER_MINIMUM_SECONDS",
    "calculate_total_with_minimum",
    "install_vip_timer_billing_guard",
]
