from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, WorkerPayout, WebOrder

router = APIRouter(tags=["admin-payout-exports"])


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def month_range(month: str | None) -> tuple[datetime | None, datetime | None]:
    if not month:
        return None, None

    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return None, None

    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)

    return start, end


def apply_date_filter(statement, model, month: str | None):
    start, end = month_range(month)

    if start is not None and end is not None:
        statement = statement.where(model.created_at >= start).where(model.created_at < end)

    return statement


def apply_status_filter(statement, model, status: str | None):
    if status in {"unpaid", "paid", "void"}:
        statement = statement.where(model.payout_status == status)

    return statement


def order_label(order: WebOrder | None, order_id: int) -> str:
    if order is None:
        return f"WEB-{order_id}"

    return order.bot_order_no or f"WEB-{order.id}"


def write_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


def csv_response(filename: str, rows: list[list[str]]) -> StreamingResponse:
    content = write_csv(rows)
    return StreamingResponse(
        iter([content.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def export_worker_rows(db: Session, *, month: str | None, status: str | None) -> list[list[str]]:
    statement = (
        select(WorkerPayout, WebOrder)
        .join(WebOrder, WebOrder.id == WorkerPayout.order_id, isouter=True)
        .order_by(WorkerPayout.created_at.desc())
    )
    statement = apply_date_filter(statement, WorkerPayout, month)
    statement = apply_status_filter(statement, WorkerPayout, status)

    rows = [[
        "類型",
        "訂單",
        "訂單ID",
        "打手ID",
        "打手名稱",
        "分攤金額",
        "基本分潤",
        "掛名加成",
        "最後實拿",
        "狀態",
        "建立時間",
        "發放時間",
        "備註",
    ]]

    for payout, order in db.execute(statement).all():
        rows.append([
            "打手",
            order_label(order, payout.order_id),
            str(payout.order_id),
            payout.worker_discord_id,
            payout.worker_display_name or "",
            str(payout.gross_share or 0),
            str(payout.base_payout or 0),
            str(payout.named_bonus_amount or 0),
            str(payout.final_payout or 0),
            payout.payout_status,
            payout.created_at.isoformat(sep=" ", timespec="seconds") if payout.created_at else "",
            payout.paid_at.isoformat(sep=" ", timespec="seconds") if payout.paid_at else "",
            payout.note or "",
        ])

    return rows


def export_customer_service_rows(db: Session, *, month: str | None, status: str | None) -> list[list[str]]:
    statement = (
        select(CustomerServicePayout, WebOrder)
        .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id, isouter=True)
        .order_by(CustomerServicePayout.created_at.desc())
    )
    statement = apply_date_filter(statement, CustomerServicePayout, month)
    statement = apply_status_filter(statement, CustomerServicePayout, status)

    rows = [[
        "類型",
        "訂單",
        "訂單ID",
        "客服ID",
        "客服名稱",
        "比例",
        "分潤金額",
        "狀態",
        "建立時間",
        "發放時間",
        "備註",
    ]]

    for payout, order in db.execute(statement).all():
        rows.append([
            "客服",
            order_label(order, payout.order_id),
            str(payout.order_id),
            payout.customer_service_discord_id,
            payout.customer_service_display_name or "",
            str(payout.rate or 0),
            str(payout.payout_amount or 0),
            payout.payout_status,
            payout.created_at.isoformat(sep=" ", timespec="seconds") if payout.created_at else "",
            payout.paid_at.isoformat(sep=" ", timespec="seconds") if payout.paid_at else "",
            payout.note or "",
        ])

    return rows


@router.get("/admin/payouts/export.csv")
async def export_payouts_csv(
    request: Request,
    month: str | None = None,
    status: str | None = None,
    role: str | None = None,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    db = SessionLocal()

    try:
        rows: list[list[str]] = []

        if role in {None, "", "all", "worker"}:
            rows.extend(export_worker_rows(db, month=month, status=status))

        if role in {None, "", "all"}:
            rows.append([])

        if role in {None, "", "all", "customer_service"}:
            rows.extend(export_customer_service_rows(db, month=month, status=status))
    finally:
        db.close()

    safe_month = month or "all"
    safe_status = status or "all"
    safe_role = role or "all"

    return csv_response(
        filename=f"payouts_{safe_month}_{safe_status}_{safe_role}.csv",
        rows=rows,
    )
