from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout

router = APIRouter(tags=["admin-payouts"])

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


def redirect_to_payouts(**params) -> RedirectResponse:
    query = {key: value for key, value in params.items() if value not in (None, "")}
    url = "/admin/payouts"
    if query:
        url = f"{url}?{urlencode(query)}"
    return RedirectResponse(url=url, status_code=303)


def parse_month(month: str | None) -> tuple[datetime | None, datetime | None]:
    if not month:
        return None, None
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_num = int(month_text)
        start = datetime(year, month_num, 1)
        if month_num == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month_num + 1, 1)
        return start, end
    except Exception:
        return None, None


def status_matches(current_status: str | None, wanted_status: str | None) -> bool:
    if not wanted_status or wanted_status == "all":
        return True
    return current_status == wanted_status


def build_group_key(role: str, discord_id: str | None, display_name: str | None) -> str:
    return f"{role}:{discord_id or display_name or 'unknown'}"


def make_empty_group(role: str, discord_id: str | None, display_name: str | None) -> dict:
    return {
        "role": role,
        "discord_id": discord_id or "",
        "display_name": display_name or discord_id or "未命名",
        "unpaid_total": 0,
        "paid_total": 0,
        "all_total": 0,
        "count": 0,
        "items": [],
    }


def add_to_group(groups: dict[str, dict], group: dict, amount: int, payout_status: str, item: dict) -> None:
    group["count"] += 1
    group["all_total"] += amount
    if payout_status == PayoutStatus.PAID.value:
        group["paid_total"] += amount
    elif payout_status == PayoutStatus.UNPAID.value:
        group["unpaid_total"] += amount
    group["items"].append(item)


def sort_groups(groups: dict[str, dict]) -> list[dict]:
    return sorted(
        groups.values(),
        key=lambda group: (group["role"], -int(group["unpaid_total"]), group["display_name"]),
    )


@router.get("/admin/payouts")
async def admin_payouts(
    request: Request,
    month: str | None = None,
    status: str = "unpaid",
    role: str = "all",
    message: str | None = None,
    error: str | None = None,
):
    user = get_current_user(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={"title": "請先登入", "message": "請先使用 Discord 登入。", "user": None},
            status_code=401,
        )
    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={"title": "沒有權限", "message": "你沒有總控後台權限。", "user": user},
            status_code=403,
        )

    month_start, month_end = parse_month(month)

    db = SessionLocal()
    try:
        groups: dict[str, dict] = {}
        summary = {
            "worker_unpaid_total": 0,
            "worker_paid_total": 0,
            "customer_service_unpaid_total": 0,
            "customer_service_paid_total": 0,
            "unpaid_total": 0,
            "paid_total": 0,
            "all_total": 0,
            "group_count": 0,
            "item_count": 0,
        }

        if role in {"all", "worker"}:
            statement = (
                select(WorkerPayout, WebOrder)
                .join(WebOrder, WebOrder.id == WorkerPayout.order_id, isouter=True)
                .order_by(WorkerPayout.worker_display_name.asc(), WorkerPayout.created_at.desc())
            )
            if month_start and month_end:
                statement = statement.where(WorkerPayout.created_at >= month_start).where(WorkerPayout.created_at < month_end)
            if status != "all":
                statement = statement.where(WorkerPayout.payout_status == status)

            for payout, order in db.execute(statement).all():
                amount = int(payout.final_payout or 0)
                payout_status = payout.payout_status or PayoutStatus.UNPAID.value
                key = build_group_key("worker", payout.worker_discord_id, payout.worker_display_name)
                groups.setdefault(key, make_empty_group("worker", payout.worker_discord_id, payout.worker_display_name))
                add_to_group(
                    groups,
                    groups[key],
                    amount,
                    payout_status,
                    {
                        "id": payout.id,
                        "role": "worker",
                        "order_id": payout.order_id,
                        "order_no": order.bot_order_no if order else f"WEB-{payout.order_id}",
                        "category": order.category if order else "",
                        "item": order.item if order else "",
                        "base_payout": int(payout.base_payout or 0),
                        "bonus": int(payout.named_bonus_amount or 0),
                        "amount": amount,
                        "status": payout_status,
                        "created_at": payout.created_at,
                        "note": payout.note or "",
                    },
                )
                summary["item_count"] += 1
                summary["all_total"] += amount
                if payout_status == PayoutStatus.PAID.value:
                    summary["worker_paid_total"] += amount
                    summary["paid_total"] += amount
                elif payout_status == PayoutStatus.UNPAID.value:
                    summary["worker_unpaid_total"] += amount
                    summary["unpaid_total"] += amount

        if role in {"all", "customer_service"}:
            statement = (
                select(CustomerServicePayout, WebOrder)
                .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id, isouter=True)
                .order_by(CustomerServicePayout.customer_service_display_name.asc(), CustomerServicePayout.created_at.desc())
            )
            if month_start and month_end:
                statement = statement.where(CustomerServicePayout.created_at >= month_start).where(CustomerServicePayout.created_at < month_end)
            if status != "all":
                statement = statement.where(CustomerServicePayout.payout_status == status)

            for payout, order in db.execute(statement).all():
                amount = int(payout.payout_amount or 0)
                payout_status = payout.payout_status or PayoutStatus.UNPAID.value
                key = build_group_key("customer_service", payout.customer_service_discord_id, payout.customer_service_display_name)
                groups.setdefault(key, make_empty_group("customer_service", payout.customer_service_discord_id, payout.customer_service_display_name))
                add_to_group(
                    groups,
                    groups[key],
                    amount,
                    payout_status,
                    {
                        "id": payout.id,
                        "role": "customer_service",
                        "order_id": payout.order_id,
                        "order_no": order.bot_order_no if order else f"WEB-{payout.order_id}",
                        "category": order.category if order else "",
                        "item": order.item if order else "",
                        "base_payout": 0,
                        "bonus": 0,
                        "amount": amount,
                        "status": payout_status,
                        "created_at": payout.created_at,
                        "note": payout.note or "",
                    },
                )
                summary["item_count"] += 1
                summary["all_total"] += amount
                if payout_status == PayoutStatus.PAID.value:
                    summary["customer_service_paid_total"] += amount
                    summary["paid_total"] += amount
                elif payout_status == PayoutStatus.UNPAID.value:
                    summary["customer_service_unpaid_total"] += amount
                    summary["unpaid_total"] += amount

        grouped_payouts = sort_groups(groups)
        summary["group_count"] = len(grouped_payouts)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_payouts.html",
        context={
            "title": "分潤明細",
            "user": user,
            "month": month or "",
            "status": status,
            "role": role,
            "message": message,
            "error": error,
            "summary": summary,
            "grouped_payouts": grouped_payouts,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
        },
    )


@router.post("/admin/payouts/group-status")
async def update_group_payout_status(
    request: Request,
    payout_role: str = Form(...),
    discord_id: str = Form(...),
    target_status: str = Form(...),
    month: str | None = Form(default=None),
    status: str = Form(default="unpaid"),
    role: str = Form(default="all"),
):
    user = require_admin_user(request)
    if not user:
        return redirect_to_payouts(error="你沒有總控後台權限，或登入狀態已過期。")
    if target_status not in {PayoutStatus.PAID.value, PayoutStatus.UNPAID.value}:
        return redirect_to_payouts(month=month, status=status, role=role, error="分潤狀態不正確。")

    month_start, month_end = parse_month(month)
    paid_at = datetime.utcnow() if target_status == PayoutStatus.PAID.value else None

    db = SessionLocal()
    try:
        updated = 0
        if payout_role == "worker":
            statement = select(WorkerPayout).where(WorkerPayout.worker_discord_id == discord_id)
            if month_start and month_end:
                statement = statement.where(WorkerPayout.created_at >= month_start).where(WorkerPayout.created_at < month_end)
            for payout in db.scalars(statement).all():
                if status_matches(payout.payout_status, status):
                    payout.payout_status = target_status
                    payout.paid_at = paid_at
                    updated += 1
        elif payout_role == "customer_service":
            statement = select(CustomerServicePayout).where(CustomerServicePayout.customer_service_discord_id == discord_id)
            if month_start and month_end:
                statement = statement.where(CustomerServicePayout.created_at >= month_start).where(CustomerServicePayout.created_at < month_end)
            for payout in db.scalars(statement).all():
                if status_matches(payout.payout_status, status):
                    payout.payout_status = target_status
                    payout.paid_at = paid_at
                    updated += 1
        else:
            return redirect_to_payouts(month=month, status=status, role=role, error="身份類型不正確。")
        db.commit()
    finally:
        db.close()

    action_text = "已發放" if target_status == PayoutStatus.PAID.value else "未發放"
    return redirect_to_payouts(month=month, status=status, role=role, message=f"已把 {updated} 筆分潤改成{action_text}。")


@router.post("/admin/payouts/single-status")
async def update_single_payout_status(
    request: Request,
    payout_role: str = Form(...),
    payout_id: int = Form(...),
    target_status: str = Form(...),
    month: str | None = Form(default=None),
    status: str = Form(default="unpaid"),
    role: str = Form(default="all"),
):
    user = require_admin_user(request)
    if not user:
        return redirect_to_payouts(error="你沒有總控後台權限，或登入狀態已過期。")
    if target_status not in {PayoutStatus.PAID.value, PayoutStatus.UNPAID.value}:
        return redirect_to_payouts(month=month, status=status, role=role, error="分潤狀態不正確。")

    db = SessionLocal()
    try:
        if payout_role == "worker":
            payout = db.get(WorkerPayout, payout_id)
        elif payout_role == "customer_service":
            payout = db.get(CustomerServicePayout, payout_id)
        else:
            payout = None
        if payout is None:
            return redirect_to_payouts(month=month, status=status, role=role, error="找不到分潤資料。")
        payout.payout_status = target_status
        payout.paid_at = datetime.utcnow() if target_status == PayoutStatus.PAID.value else None
        db.commit()
    finally:
        db.close()

    return redirect_to_payouts(month=month, status=status, role=role, message="分潤狀態已更新。")
