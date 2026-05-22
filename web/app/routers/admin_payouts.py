from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class PayoutTotals:
    worker_unpaid: int = 0
    worker_paid: int = 0
    customer_service_unpaid: int = 0
    customer_service_paid: int = 0
    worker_count: int = 0
    customer_service_count: int = 0

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


def _parse_month(month: str | None) -> tuple[datetime, datetime] | None:
    if not month:
        return None

    try:
        year_str, month_str = month.split("-", 1)
        year = int(year_str)
        month_number = int(month_str)
        start = datetime(year, month_number, 1)
        if month_number == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month_number + 1, 1)
        return start, end
    except Exception:
        return None


def _matches_month(created_at: datetime | None, month_range: tuple[datetime, datetime] | None) -> bool:
    if month_range is None:
        return True

    if created_at is None:
        return False

    start, end = month_range
    return start <= created_at < end


def list_worker_payout_rows(
    db: Session,
    *,
    month: str | None,
    status: str,
) -> list[tuple[WorkerPayout, WebOrder | None]]:
    statement = (
        select(WorkerPayout, WebOrder)
        .join(WebOrder, WebOrder.id == WorkerPayout.order_id, isouter=True)
        .order_by(WorkerPayout.updated_at.desc(), WorkerPayout.id.desc())
    )

    rows = list(db.execute(statement).all())
    month_range = _parse_month(month)

    filtered_rows: list[tuple[WorkerPayout, WebOrder | None]] = []

    for payout, order in rows:
        if status != "all" and payout.payout_status != status:
            continue

        if not _matches_month(payout.created_at, month_range):
            continue

        filtered_rows.append((payout, order))

    return filtered_rows


def list_customer_service_payout_rows(
    db: Session,
    *,
    month: str | None,
    status: str,
) -> list[tuple[CustomerServicePayout, WebOrder | None]]:
    statement = (
        select(CustomerServicePayout, WebOrder)
        .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id, isouter=True)
        .order_by(CustomerServicePayout.updated_at.desc(), CustomerServicePayout.id.desc())
    )

    rows = list(db.execute(statement).all())
    month_range = _parse_month(month)

    filtered_rows: list[tuple[CustomerServicePayout, WebOrder | None]] = []

    for payout, order in rows:
        if status != "all" and payout.payout_status != status:
            continue

        if not _matches_month(payout.created_at, month_range):
            continue

        filtered_rows.append((payout, order))

    return filtered_rows


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
    month: str | None = None,
    status: str = "all",
    role: str = "all",
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

    if status not in {"all", PayoutStatus.UNPAID.value, PayoutStatus.PAID.value}:
        status = "all"

    if role not in {"all", "worker", "customer_service"}:
        role = "all"

    db = SessionLocal()

    try:
        worker_rows = []
        customer_service_rows = []

        if role in {"all", "worker"}:
            worker_rows = list_worker_payout_rows(db, month=month, status=status)

        if role in {"all", "customer_service"}:
            customer_service_rows = list_customer_service_payout_rows(db, month=month, status=status)

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
            "selected_month": month or "",
            "selected_status": status,
            "selected_role": role,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/payouts/worker/{payout_id}/status")
async def admin_set_worker_payout_status_from_payouts(
    request: Request,
    payout_id: int,
    status: str = Form(...),
    month: str | None = Form(default=None),
    current_status: str = Form(default="all"),
    role: str = Form(default="all"),
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
        return redirect_to_admin_payouts(error=str(e), month=month, status=current_status, role=role)
    finally:
        db.close()

    return redirect_to_admin_payouts(
        message="打手分潤狀態已更新。",
        month=month,
        status=current_status,
        role=role,
    )


@router.post("/admin/payouts/customer-service/{payout_id}/status")
async def admin_set_customer_service_payout_status_from_payouts(
    request: Request,
    payout_id: int,
    status: str = Form(...),
    month: str | None = Form(default=None),
    current_status: str = Form(default="all"),
    role: str = Form(default="all"),
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
        return redirect_to_admin_payouts(error=str(e), month=month, status=current_status, role=role)
    finally:
        db.close()

    return redirect_to_admin_payouts(
        message="客服分潤狀態已更新。",
        month=month,
        status=current_status,
        role=role,
    )


@router.post("/admin/payouts/bulk-status")
async def admin_bulk_set_payout_status(
    request: Request,
    target_status: str = Form(...),
    payout_type: str = Form(default="all"),
    month: str | None = Form(default=None),
    current_status: str = Form(default="all"),
    role: str = Form(default="all"),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin_payouts(error="你沒有總控後台權限，或登入狀態已過期。")

    if target_status not in {PayoutStatus.UNPAID.value, PayoutStatus.PAID.value}:
        return redirect_to_admin_payouts(error="分潤狀態不正確。", month=month, status=current_status, role=role)

    if payout_type not in {"all", "worker", "customer_service"}:
        payout_type = "all"

    db = SessionLocal()

    try:
        changed_count = 0

        if payout_type in {"all", "worker"}:
            worker_rows = list_worker_payout_rows(
                db,
                month=month,
                status=PayoutStatus.UNPAID.value if target_status == PayoutStatus.PAID.value else PayoutStatus.PAID.value,
            )
            for payout, _order in worker_rows:
                set_worker_payout_status(
                    db,
                    payout_id=payout.id,
                    status=target_status,
                    admin_user=user,
                )
                changed_count += 1

        if payout_type in {"all", "customer_service"}:
            customer_service_rows = list_customer_service_payout_rows(
                db,
                month=month,
                status=PayoutStatus.UNPAID.value if target_status == PayoutStatus.PAID.value else PayoutStatus.PAID.value,
            )
            for payout, _order in customer_service_rows:
                set_customer_service_payout_status(
                    db,
                    payout_id=payout.id,
                    status=target_status,
                    admin_user=user,
                )
                changed_count += 1
    except ValueError as e:
        db.rollback()
        return redirect_to_admin_payouts(error=str(e), month=month, status=current_status, role=role)
    finally:
        db.close()

    return redirect_to_admin_payouts(
        message=f"批量更新完成，共 {changed_count} 筆。",
        month=month,
        status="all",
        role=role,
    )
