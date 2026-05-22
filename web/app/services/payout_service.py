from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout


def list_worker_payouts_for_user(
    db: Session,
    *,
    worker_discord_id: str,
) -> list[tuple[WorkerPayout, WebOrder | None]]:
    statement = (
        select(WorkerPayout, WebOrder)
        .join(WebOrder, WebOrder.id == WorkerPayout.order_id, isouter=True)
        .where(WorkerPayout.worker_discord_id == str(worker_discord_id))
        .order_by(WorkerPayout.created_at.desc())
    )

    return list(db.execute(statement).all())


def list_customer_service_payouts_for_user(
    db: Session,
    *,
    customer_service_discord_id: str,
) -> list[tuple[CustomerServicePayout, WebOrder | None]]:
    statement = (
        select(CustomerServicePayout, WebOrder)
        .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id, isouter=True)
        .where(CustomerServicePayout.customer_service_discord_id == str(customer_service_discord_id))
        .order_by(CustomerServicePayout.created_at.desc())
    )

    return list(db.execute(statement).all())


def build_payout_summary(
    *,
    worker_rows: list[tuple[WorkerPayout, WebOrder | None]],
    customer_service_rows: list[tuple[CustomerServicePayout, WebOrder | None]],
) -> dict:
    worker_unpaid_total = 0
    worker_paid_total = 0

    for payout, _order in worker_rows:
        if payout.payout_status == PayoutStatus.PAID.value:
            worker_paid_total += int(payout.final_payout or 0)
        elif payout.payout_status == PayoutStatus.UNPAID.value:
            worker_unpaid_total += int(payout.final_payout or 0)

    customer_service_unpaid_total = 0
    customer_service_paid_total = 0

    for payout, _order in customer_service_rows:
        if payout.payout_status == PayoutStatus.PAID.value:
            customer_service_paid_total += int(payout.payout_amount or 0)
        elif payout.payout_status == PayoutStatus.UNPAID.value:
            customer_service_unpaid_total += int(payout.payout_amount or 0)

    unpaid_total = worker_unpaid_total + customer_service_unpaid_total
    paid_total = worker_paid_total + customer_service_paid_total

    return {
        "worker_unpaid_total": worker_unpaid_total,
        "worker_paid_total": worker_paid_total,
        "customer_service_unpaid_total": customer_service_unpaid_total,
        "customer_service_paid_total": customer_service_paid_total,
        "unpaid_total": unpaid_total,
        "paid_total": paid_total,
        "all_total": unpaid_total + paid_total,
        "worker_count": len(worker_rows),
        "customer_service_count": len(customer_service_rows),
    }