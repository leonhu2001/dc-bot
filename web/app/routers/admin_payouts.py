from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout
from web.app.services.admin_service import (
    set_customer_service_payout_status,
    set_worker_payout_status,
)

router = APIRouter(tags=["admin-payouts"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class PayoutTotals:
    def __init__(self) -> None:
        self.worker_unpaid = 0
        self.worker_paid = 0
        self.customer_service_unpaid = 0
        self.customer_service_paid = 0
        self.worker_count = 0
        self.customer_service_count = 0

    @property
    def unpaid_total(self) -> int:
        return self.worker_unpaid + self.customer_service_unpaid

    @property
    def paid_total(self) -> int:
        return self.worker_paid + self.customer_service_paid

    @property
    def all_total(self) -> int:
        return self.unpaid_total + self.paid_total


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def redirect_to_admin_payouts(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin/payouts?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin/payouts", status_code=303)


def list_worker_payout_rows(db: Session) -> list[tuple[WorkerPayout, WebOrder | None]]:
    statement = (
        select(WorkerPayout, WebOrder)
        .join(WebOrder, WebOrder.id == WorkerPayout.order_id, isouter=True)
        .order_by(WorkerPayout.updated_at.desc(), WorkerPayout.id.desc())
    )

    return list(db.execute(statement).all())


def list_customer_service_payout_rows(
    db: Session,
) -> list[tuple[CustomerServicePayout, WebOrder | None]]:
    statement = (
        select(CustomerServicePayout, WebOrder)
        .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id, isouter=True)
        .order_by(CustomerServicePayout.updated_at.desc(), CustomerServicePayout.id.desc())
    )

    return list(db.execute(statement).all())


def build_totals(
    *,
    worker_rows: list[tuple[WorkerPayout, WebOrder | None]],
    customer_service_rows: list[tuple[CustomerServicePayout, WebOrder | None]],
) -> PayoutTotals:
    totals = PayoutTotals()
    totals.worker_count = len(worker_rows)
    totals.customer_service_count = len(customer_service_rows)

    for payout, _order in worker_rows:
        amount = int(payout.final_payout or 0)
        if payout.payout_status == PayoutStatus.PAID.value:
            totals.worker_paid += amount
        elif payout.payout_status == PayoutStatus.UNPAID.value:
            totals.worker_unpaid += amount

    for payout, _order in customer_service_rows:
        amount = int(payout.payout_amount or 0)
        if payout.payout_status == PayoutStatus.PAID.value:
            totals.customer_service_paid += amount
        elif payout.payout_status == PayoutStatus.UNPAID.value:
            totals.customer_service_unpaid += amount

    return totals


@router.get("/admin/payouts")
async def admin_payouts(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = get_current_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        worker_rows = list_worker_payout_rows(db)
        customer_service_rows = list_customer_service_payout_rows(db)
        totals = build_totals(
            worker_rows=worker_rows,
            customer_service_rows=customer_service_rows,
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_payouts.html",
        context={
            "title": "分潤總表",
            "user": user,
            "worker_rows": worker_rows,
            "customer_service_rows": customer_service_rows,
            "totals": totals,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/payouts/worker/{payout_id}/status")
async def admin_set_worker_payout_status_from_payouts(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin_payouts(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin_payouts(error=str(e))
    finally:
        db.close()

    return redirect_to_admin_payouts(message="打手分潤狀態已更新。")


@router.post("/admin/payouts/customer-service/{payout_id}/status")
async def admin_set_customer_service_payout_status_from_payouts(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin_payouts(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_customer_service_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin_payouts(error=str(e))
    finally:
        db.close()

    return redirect_to_admin_payouts(message="客服分潤狀態已更新。")
