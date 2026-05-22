from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import SessionLocal
from shared.models import OrderStatus, WebOrder

router = APIRouter(tags=["order-history"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/admin/orders/history")
async def admin_order_history(
    request: Request,
    status: str | None = None,
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

    allowed_statuses = {
        OrderStatus.STORED.value,
        OrderStatus.CLOSED.value,
        OrderStatus.CANCELLED.value,
    }

    selected_status = status if status in allowed_statuses else "all"

    db = SessionLocal()

    try:
        statement = (
            select(WebOrder)
            .where(WebOrder.status != OrderStatus.ACTIVE.value)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
            .order_by(WebOrder.updated_at.desc(), WebOrder.created_at.desc())
        )

        if selected_status != "all":
            statement = statement.where(WebOrder.status == selected_status)

        orders = list(db.scalars(statement).all())
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="order_history.html",
        context={
            "title": "歷史訂單",
            "user": user,
            "orders": orders,
            "selected_status": selected_status,
            "stored_status": OrderStatus.STORED.value,
            "closed_status": OrderStatus.CLOSED.value,
            "cancelled_status": OrderStatus.CANCELLED.value,
        },
    )
