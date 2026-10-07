from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.db import SessionLocal
from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
from web.app.services.dispatch_access import (
    can_use_dispatch,
    touch_dispatch_user_presence,
)
from web.app.config import config
from web.app.services.dispatch_support import (
    assign_companion_from_dispatch,
    can_manage_dispatch_orders,
)
from web.app.services.order_service import (
    claim_order_for_worker,
    create_demo_orders_if_empty,
    get_worker_active_order_count,
    get_worker_active_order_ids,
    get_worker_dispatch_payout_preview,
    list_active_orders,
    partition_dispatch_orders,
    unclaim_order_for_worker,
)
from web.app.services.staff_service import list_companion_members

router = APIRouter(tags=["dispatch"])


def get_dispatch_role_type(user: dict | None) -> str:
    # 網站派單頁不再分舊職位名稱，統一視為接單人員。
    return "booster"


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


def keep_protected_orders_on_available_board(
    claimable_orders,
    non_claimable_orders,
):
    protected_orders = [
        order
        for order in non_claimable_orders
        if (
            str(getattr(order, "status", "") or "") == "waiting_acceptance"
            and int(getattr(order, "dispatch_missing_staff_count", 0) or 0) > 0
            and bool(getattr(order, "dispatch_acceptance_locked", False))
        )
    ]
    protected_ids = {int(order.id) for order in protected_orders}

    return (
        [*claimable_orders, *protected_orders],
        [
            order
            for order in non_claimable_orders
            if int(order.id) not in protected_ids
        ],
    )


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

    touch_dispatch_user_presence(user)
    support_can_manage = can_manage_dispatch_orders(user)
    user_can_claim = bool(
        user.get("is_worker")
        or user.get("is_companion")
    )

    db = SessionLocal()

    try:
        create_demo_orders_if_empty(db)
        orders = list_active_orders(db)
        claimable_orders, non_claimable_orders = partition_dispatch_orders(orders)
        claimable_orders, non_claimable_orders = keep_protected_orders_on_available_board(
            claimable_orders,
            non_claimable_orders,
        )
        orders = [*claimable_orders, *non_claimable_orders]
        active_order_count = get_worker_active_order_count(db, str(user["id"]))
        claimed_order_ids = get_worker_active_order_ids(db, str(user["id"]))
        claimed_orders = [order for order in orders if order.id in claimed_order_ids]
        companion_options = (
            list_companion_members(db)
            if support_can_manage
            else []
        )

        guild_id = str(config.DISCORD_GUILD_ID or "").strip()
        claimed_order_summaries = {}

        for order in claimed_orders:
            payout_preview = get_worker_dispatch_payout_preview(
                order,
                str(user["id"]),
            )
            ticket_channel_id = str(
                getattr(order, "ticket_channel_id", "")
                or ""
            ).strip()
            dispatch_channel_id = str(
                getattr(order, "dispatch_channel_id", "")
                or ""
            ).strip()
            dispatch_message_id = str(
                getattr(order, "dispatch_message_id", "")
                or ""
            ).strip()

            ticket_url = None
            if guild_id and ticket_channel_id:
                ticket_url = (
                    f"https://discord.com/channels/{guild_id}/"
                    f"{ticket_channel_id}"
                )

            dispatch_url = None
            if guild_id and dispatch_channel_id and dispatch_message_id:
                dispatch_url = (
                    f"https://discord.com/channels/{guild_id}/"
                    f"{dispatch_channel_id}/{dispatch_message_id}"
                )

            claimed_order_summaries[int(order.id)] = {
                "status_label": getattr(
                    order,
                    "dispatch_status_label",
                    str(getattr(order, "status", "") or ""),
                ),
                "current_staff_count": int(
                    getattr(order, "dispatch_current_staff_count", 0)
                    or 0
                ),
                "required_staff_count": int(
                    getattr(order, "dispatch_required_staff_count", 0)
                    or 0
                ),
                "missing_staff_count": int(
                    getattr(order, "dispatch_missing_staff_count", 0)
                    or 0
                ),
                "payout": payout_preview,
                "ticket_url": ticket_url,
                "dispatch_url": dispatch_url,
            }
    finally:
        db.close()

    online_companion_count = count_online_dispatch_workers()
    online_support_count = len(get_online_dispatch_support_ids())

    return templates.TemplateResponse(
        request=request,
        name="dispatch.html",
        context={
            "title": "派單頁面",
            "user": user,
            "orders": orders,
            "claimable_orders": claimable_orders,
            "non_claimable_orders": non_claimable_orders,
            "online_companion_count": online_companion_count,
            "online_support_count": online_support_count,
            "active_order_count": active_order_count,
            "claimed_order_ids": claimed_order_ids,
            "claimed_orders": claimed_orders,
            "claimed_order_summaries": claimed_order_summaries,
            "support_can_manage": support_can_manage,
            "user_can_claim": user_can_claim,
            "companion_options": companion_options,
            "message": message,
            "error": error,
        },
    )


@router.post("/dispatch/orders/{order_id}/claim")
async def claim_order(request: Request, order_id: int):
    user = require_dispatch_user(request)

    if not user:
        return redirect_to_dispatch(error="你沒有派單頁面權限，或登入狀態已過期。")

    if not (user.get("is_worker") or user.get("is_companion")):
        return redirect_to_dispatch(error="客服請使用客服操作區指派陪玩。")

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

    if not (user.get("is_worker") or user.get("is_companion")):
        return redirect_to_dispatch(error="客服不能以接單人員身分取消接單。")

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


@router.post("/dispatch/orders/{order_id}/support-assign")
async def support_assign_companion(
    request: Request,
    order_id: int,
    companion_discord_id: str = Form(...),
):
    user = require_dispatch_user(request)

    if not user or not can_manage_dispatch_orders(user):
        return redirect_to_dispatch(error="你沒有客服派單操作權限。")

    db = SessionLocal()

    try:
        result_message = assign_companion_from_dispatch(
            db,
            order_id=order_id,
            companion_discord_id=companion_discord_id,
            support_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_dispatch(error=str(e))
    finally:
        db.close()

    return redirect_to_dispatch(message=result_message)