from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, WorkerPayout

router = APIRouter(tags=["admin-payout-summary"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def redirect_to_summary(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin/payouts/summary?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin/payouts/summary", status_code=303)


def parse_month_range(month: str | None) -> tuple[datetime | None, datetime | None]:
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


def empty_person_row(*, discord_id: str, display_name: str, role: str) -> dict:
    return {
        "discord_id": discord_id,
        "display_name": display_name or discord_id,
        "role": role,
        "unpaid_total": 0,
        "paid_total": 0,
        "all_total": 0,
        "unpaid_count": 0,
        "paid_count": 0,
        "all_count": 0,
    }


def apply_date_filter(statement, model, month: str | None):
    start, end = parse_month_range(month)

    if start is not None:
        statement = statement.where(model.created_at >= start)

    if end is not None:
        statement = statement.where(model.created_at < end)

    return statement


def apply_status_filter(statement, model, status: str | None):
    if status in {PayoutStatus.PAID.value, PayoutStatus.UNPAID.value}:
        statement = statement.where(model.payout_status == status)

    return statement


def build_summary_rows(
    *,
    month: str | None,
    status: str | None,
    role: str | None,
) -> tuple[list[dict], dict]:
    rows_by_key: dict[tuple[str, str], dict] = {}

    db = SessionLocal()

    try:
        if role in {None, "", "all", "worker"}:
            worker_statement = select(WorkerPayout)
            worker_statement = apply_date_filter(worker_statement, WorkerPayout, month)
            worker_statement = apply_status_filter(worker_statement, WorkerPayout, status)

            for payout in db.scalars(worker_statement).all():
                key = ("worker", str(payout.worker_discord_id))
                row = rows_by_key.setdefault(
                    key,
                    empty_person_row(
                        discord_id=str(payout.worker_discord_id),
                        display_name=payout.worker_display_name or str(payout.worker_discord_id),
                        role="打手",
                    ),
                )

                amount = int(payout.final_payout or 0)
                row["all_total"] += amount
                row["all_count"] += 1

                if payout.payout_status == PayoutStatus.PAID.value:
                    row["paid_total"] += amount
                    row["paid_count"] += 1
                elif payout.payout_status == PayoutStatus.UNPAID.value:
                    row["unpaid_total"] += amount
                    row["unpaid_count"] += 1

        if role in {None, "", "all", "customer_service"}:
            service_statement = select(CustomerServicePayout)
            service_statement = apply_date_filter(service_statement, CustomerServicePayout, month)
            service_statement = apply_status_filter(service_statement, CustomerServicePayout, status)

            for payout in db.scalars(service_statement).all():
                key = ("customer_service", str(payout.customer_service_discord_id))
                row = rows_by_key.setdefault(
                    key,
                    empty_person_row(
                        discord_id=str(payout.customer_service_discord_id),
                        display_name=payout.customer_service_display_name or str(payout.customer_service_discord_id),
                        role="客服",
                    ),
                )

                amount = int(payout.payout_amount or 0)
                row["all_total"] += amount
                row["all_count"] += 1

                if payout.payout_status == PayoutStatus.PAID.value:
                    row["paid_total"] += amount
                    row["paid_count"] += 1
                elif payout.payout_status == PayoutStatus.UNPAID.value:
                    row["unpaid_total"] += amount
                    row["unpaid_count"] += 1
    finally:
        db.close()

    rows = sorted(
        rows_by_key.values(),
        key=lambda item: (item["role"], -item["unpaid_total"], item["display_name"]),
    )

    totals = {
        "unpaid_total": sum(row["unpaid_total"] for row in rows),
        "paid_total": sum(row["paid_total"] for row in rows),
        "all_total": sum(row["all_total"] for row in rows),
        "unpaid_count": sum(row["unpaid_count"] for row in rows),
        "paid_count": sum(row["paid_count"] for row in rows),
        "all_count": sum(row["all_count"] for row in rows),
        "person_count": len(rows),
    }

    return rows, totals


@router.get("/admin/payouts/summary")
async def admin_payout_summary(
    request: Request,
    month: str | None = None,
    status: str | None = "unpaid",
    role: str | None = "all",
):
    user = require_admin_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": get_current_user(request),
            },
            status_code=403,
        )

    rows, totals = build_summary_rows(month=month, status=status, role=role)

    return templates.TemplateResponse(
        request=request,
        name="admin_payout_summary.html",
        context={
            "title": "分潤人員總表",
            "user": user,
            "rows": rows,
            "totals": totals,
            "month": month or "",
            "status": status or "all",
            "role": role or "all",
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
        },
    )


@router.get("/admin/payouts/summary.csv")
async def admin_payout_summary_csv(
    request: Request,
    month: str | None = None,
    status: str | None = "unpaid",
    role: str | None = "all",
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    rows, totals = build_summary_rows(month=month, status=status, role=role)

    lines = [
        "身份,Discord ID,名稱,未發放總額,已發放總額,累計總額,未發放筆數,已發放筆數,累計筆數"
    ]

    for row in rows:
        values = [
            row["role"],
            row["discord_id"],
            row["display_name"],
            str(row["unpaid_total"]),
            str(row["paid_total"]),
            str(row["all_total"]),
            str(row["unpaid_count"]),
            str(row["paid_count"]),
            str(row["all_count"]),
        ]
        safe_values = [value.replace('"', '""') for value in values]
        lines.append(",".join(f'"{value}"' for value in safe_values))

    lines.append(
        f'"合計","","","{totals["unpaid_total"]}","{totals["paid_total"]}","{totals["all_total"]}","{totals["unpaid_count"]}","{totals["paid_count"]}","{totals["all_count"]}"'
    )

    csv_text = "\ufeff" + "\n".join(lines) + "\n"
    filename = f"payout_summary_{month or 'all'}_{role or 'all'}_{status or 'all'}.csv"

    return StreamingResponse(
        iter([csv_text.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
