from __future__ import annotations

"""Compatibility facade for order operations and payout-policy cutover.

All order behavior remains in ``order_service_legacy``.  Only payout
recalculation is overridden so orders created before the 2026-10-17 financial
policy keep the historical 5% customer-service payout, while new-policy orders
use 25% of the positive margin pool.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.financial_policy import uses_current_financial_policy
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import calculate_order_payout
from web.app.services import order_service_legacy as _legacy
from web.app.services.order_service_legacy import *  # noqa: F401,F403


def recalculate_order_payouts(db: Session, order_id: int) -> None:
    order = db.get(WebOrder, order_id)
    if order is None:
        raise ValueError("找不到這張訂單，無法計算分潤。")

    _legacy.ensure_not_unpaid_prepay_order_for_legacy_assignment(
        db,
        order,
        action_label="計算分潤",
    )

    assignments = list(
        db.scalars(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order_id)
            .where(OrderAssignment.is_active.is_(True))
            .order_by(OrderAssignment.assigned_at.asc())
        ).all()
    )

    worker_ids = [assignment.worker_discord_id for assignment in assignments]
    named_bonus_worker_ids = [
        assignment.worker_discord_id
        for assignment in assignments
        if assignment.has_named_bonus
    ]

    current_policy = uses_current_financial_policy(
        getattr(order, "price_snapshot_json", None)
    )
    payout_result = calculate_order_payout(
        total_amount=int(
            getattr(order, "payout_base_amount", None)
            or order.amount
            or 0
        ),
        worker_discord_ids=worker_ids,
        named_bonus_worker_ids=named_bonus_worker_ids,
        customer_service_total_amount=_legacy._customer_service_payout_base(order),
        legacy_customer_service_flat=not current_policy,
    )

    overrides = {
        override.worker_discord_id: override
        for override in db.scalars(
            select(WorkerPayoutOverride)
            .where(WorkerPayoutOverride.order_id == order_id)
        ).all()
    }

    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order_id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order_id))

    assignment_name_map = {
        assignment.worker_discord_id: assignment.worker_display_name
        for assignment in assignments
    }

    for worker_payout in payout_result.worker_payouts:
        override = overrides.get(worker_payout.worker_discord_id)
        final_payout = worker_payout.final_payout
        note = None

        if override is not None:
            final_payout = int(override.manual_final_payout or 0)
            note = f"手動指定分潤：{final_payout}T"
            if override.reason:
                note += f"｜原因：{override.reason}"

        db.add(
            WorkerPayout(
                order_id=order_id,
                worker_discord_id=worker_payout.worker_discord_id,
                worker_display_name=assignment_name_map.get(worker_payout.worker_discord_id),
                gross_share=worker_payout.gross_share,
                base_rate=worker_payout.base_rate,
                base_payout=worker_payout.base_payout,
                named_bonus_rate=worker_payout.named_bonus_rate,
                named_bonus_amount=worker_payout.named_bonus_amount,
                has_named_bonus=worker_payout.has_named_bonus,
                final_payout=final_payout,
                payout_status=PayoutStatus.UNPAID.value,
                note=note,
            )
        )

    customer_service_discord_id = (
        str(order.customer_service_discord_id)
        if order.customer_service_discord_id
        else "demo_customer_service"
    )
    customer_service_display_name = order.customer_service_display_name or "測試客服"

    db.add(
        CustomerServicePayout(
            order_id=order_id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            rate=payout_result.customer_service_rate,
            payout_amount=payout_result.customer_service_payout,
            payout_status=PayoutStatus.UNPAID.value,
        )
    )


# Existing functions in the preserved module look this name up from their own
# globals at runtime. Patch it so claim/assignment flows cannot bypass cutover.
_legacy.recalculate_order_payouts = recalculate_order_payouts
