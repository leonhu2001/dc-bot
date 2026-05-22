from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.db import SessionLocal
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_manual_worker_payout,
    toggle_named_bonus_for_assignment,
)
from web.app.services.order_service import create_demo_orders_if_empty, list_admin_orders

router = APIRouter(tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_admin(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin", status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


@router.get("/admin")
async def admin_dashboard(
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
        create_demo_orders_if_empty(db)
        orders = list_admin_orders(db)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "title": "總控後台",
            "user": user,
            "orders": orders,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/assignments/{assignment_id}/named-bonus")
async def update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        toggle_named_bonus_for_assignment(
            db,
            assignment_id=assignment_id,
            enabled=enabled == "on",
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="掛名加成已更新。")


@router.post("/admin/assignments/{assignment_id}/remove")
async def admin_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        remove_worker_from_order(
            db,
            assignment_id=assignment_id,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已移除這位打手，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/add-worker")
async def admin_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        add_worker_to_order(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已新增/更換打手，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/manual-payout")
async def admin_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_manual_worker_payout(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            manual_final_payout=manual_final_payout,
            reason=reason,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已手動更新打手分潤金額。")