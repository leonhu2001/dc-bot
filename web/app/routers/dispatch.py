from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from shared.db import SessionLocal
from web.app.services.order_service import (
    create_demo_orders_if_empty,
    get_worker_active_order_count,
    list_active_orders,
)

router = APIRouter(tags=["dispatch"])

templates = Jinja2Templates(directory="web/app/templates")


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/dispatch")
async def dispatch_dashboard(request: Request):
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

    if not user.get("is_worker") and not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有派單頁面權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        create_demo_orders_if_empty(db)
        orders = list_active_orders(db)
        active_order_count = get_worker_active_order_count(db, str(user["id"]))
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="dispatch.html",
        context={
            "title": "派單頁面",
            "user": user,
            "orders": orders,
            "active_order_count": active_order_count,
        },
    )