from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, OrderAssignment, OrderStatus, PayoutStatus, WebOrder
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
)

router = APIRouter(tags=["order-history"])

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


def redirect_to_history(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin/orders/history?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin/orders/history", status_code=303)


def list_history_orders(
    *,
    status_filter: str = "all",
    keyword: str | None = None,
) -> list[WebOrder]:
    db = SessionLocal()

    try:
        statement = (
            select(WebOrder)
            .where(WebOrder.status != OrderStatus.ACTIVE.value)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
            .order_by(WebOrder.updated_at.desc(), WebOrder.created_at.desc())
        )

        if status_filter and status_filter != "all":
            statement = statement.where(WebOrder.status == status_filter)

        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            statement = statement.where(
                WebOrder.bot_order_no.like(like_keyword)
                | WebOrder.customer_display_name.like(like_keyword)
                | WebOrder.customer_discord_id.like(like_keyword)
                | WebOrder.category.like(like_keyword)
                | WebOrder.item.like(like_keyword)
            )

        return list(db.scalars(statement).all())
    finally:
        db.close()


@router.get("/admin/orders/history")
async def admin_order_history(
    request: Request,
    status: str = "all",
    keyword: str | None = None,
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
        orders = list_history_orders(status_filter=status, keyword=keyword)
        customer_service_members = list_customer_service_members(db)
        worker_members = list_worker_members(db)

        order_ids = [order.id for order in orders]
        customer_service_payouts_by_order: dict[int, list[CustomerServicePayout]] = {}

        if order_ids:
            service_payouts = list(
                db.scalars(
                    select(CustomerServicePayout)
                    .where(CustomerServicePayout.order_id.in_(order_ids))
                    .order_by(CustomerServicePayout.id.asc())
                ).all()
            )

            for payout in service_payouts:
                customer_service_payouts_by_order.setdefault(payout.order_id, []).append(payout)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="order_history.html",
        context={
            "title": "歷史訂單",
            "user": user,
            "orders": orders,
            "current_status": status,
            "keyword": keyword or "",
            "message": message,
            "error": error,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "customer_service_payouts_by_order": customer_service_payouts_by_order,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "status_options": [
                ("all", "全部"),
                (OrderStatus.CLOSED.value, "已結單"),
                (OrderStatus.STORED.value, "存單"),
                (OrderStatus.CANCELLED.value, "取消"),
            ],
        },
    )


@router.post("/admin/orders/history/{order_id}/customer-service")
async def history_set_customer_service(
    request: Request,
    order_id: int,
    customer_service_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=customer_service_discord_id)
        customer_service_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else customer_service_discord_id
        )

        set_customer_service_for_order(
            db,
            order_id=order_id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已更新歷史訂單對接客服，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/add-worker")
async def history_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=worker_discord_id)
        worker_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else worker_discord_id
        )

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已新增歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/assignments/{assignment_id}/named-bonus")
async def history_update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="歷史訂單掛名加成已更新。")


@router.post("/admin/orders/history/assignments/{assignment_id}/remove")
async def history_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已移除歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/manual-payout")
async def history_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已手動更新歷史訂單分潤。")


@router.post("/admin/orders/history/worker-payouts/{payout_id}/status")
async def history_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(db, payout_id=payout_id, status=status, admin_user=user)
    except ValueError as e:
        db.rollback()
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="打手/陪玩分潤狀態已更新。")


@router.post("/admin/orders/history/customer-service-payouts/{payout_id}/status")
async def history_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="客服分潤狀態已更新。")
