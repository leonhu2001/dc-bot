from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.db import SessionLocal
from web.app.services.order_service import (
    claim_order_for_worker,
    create_demo_orders_if_empty,
    get_worker_active_order_count,
    get_worker_active_order_ids,
    list_active_orders,
    unclaim_order_for_worker,
)

router = APIRouter(tags=["dispatch"])


def can_use_dispatch(user: dict | None) -> bool:
    if not user:
        return False

    return bool(
        user.get("is_admin")
        or user.get("is_worker")
        or user.get("is_companion")
        or user.get("is_customer_service")
    )


def get_dispatch_role_type(user: dict | None) -> str:
    if not user:
        return "worker"

    if user.get("is_companion"):
        return "companion"

    return "worker"


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_dispatch(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/dispatch?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/dispatch", status_code=303)


def require_dispatch_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not can_use_dispatch(user):
        return None

    return user


@router.get("/dispatch")
async def dispatch_dashboard(
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

    if not can_use_dispatch(user):
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
        claimed_order_ids = get_worker_active_order_ids(db, str(user["id"]))
        claimed_orders = [order for order in orders if order.id in claimed_order_ids]
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
            "claimed_order_ids": claimed_order_ids,
            "claimed_orders": claimed_orders,
            "message": message,
            "error": error,
        },
    )


@router.post("/dispatch/orders/{order_id}/claim")
async def claim_order(request: Request, order_id: int):
    user = require_dispatch_user(request)

    if not user:
        return redirect_to_dispatch(error="你沒有派單頁面權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        claim_order_for_worker(
            db,
            order_id=order_id,
            user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_dispatch(error=str(e))
    finally:
        db.close()

    return redirect_to_dispatch(message="接單成功。")


@router.post("/dispatch/orders/{order_id}/unclaim")
async def unclaim_order(request: Request, order_id: int):
    user = require_dispatch_user(request)

    if not user:
        return redirect_to_dispatch(error="你沒有派單頁面權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        unclaim_order_for_worker(
            db,
            order_id=order_id,
            user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_dispatch(error=str(e))
    finally:
        db.close()

    return redirect_to_dispatch(message="已取消接單。")