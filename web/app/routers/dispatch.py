import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from shared.db import SessionLocal
from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
from services.order_reports import (
    REPORT_APPROVED,
    REPORT_CHANGES_REQUESTED,
    REPORT_PENDING,
    REPORT_SUBMITTED,
    ensure_order_report_tables,
    get_report_counts,
    get_report_status_map,
    list_reports_for_review,
    list_reports_for_user,
    process_pending_report_notifications,
    review_order_report,
    send_manual_report_reminder,
    submit_order_report,
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
from web.app.services.dispatch_claim_access import decorate_dispatch_order
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
_order_report_notification_task: asyncio.Task | None = None


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


def redirect_to_reports(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    url = "/reports"
    if query:
        url += "?" + urlencode(query)
    return RedirectResponse(url=url, status_code=303)


def redirect_to_report_review(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    url = "/reports/review"
    if query:
        url += "?" + urlencode(query)
    return RedirectResponse(url=url, status_code=303)


def require_dispatch_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not can_use_dispatch(user):
        return None

    return user


def require_report_reviewer(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return None
    return user


def _form_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


async def _order_report_notification_loop() -> None:
    while True:
        try:
            ensure_order_report_tables()
            await run_in_threadpool(process_pending_report_notifications, 10)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                "[order-reports] notification worker failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        await asyncio.sleep(8)


@router.on_event("startup")
async def start_order_report_notification_worker() -> None:
    global _order_report_notification_task

    try:
        ensure_order_report_tables()
    except Exception as exc:
        # Fresh databases may not have web_orders yet when router startup fires.
        # The background worker retries after canonical DB initialization.
        print(
            "[order-reports] schema init deferred: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    if (
        _order_report_notification_task is None
        or _order_report_notification_task.done()
    ):
        _order_report_notification_task = asyncio.create_task(
            _order_report_notification_loop()
        )


@router.on_event("shutdown")
async def stop_order_report_notification_worker() -> None:
    global _order_report_notification_task

    task = _order_report_notification_task
    _order_report_notification_task = None
    if task is None:
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


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
        for order in orders:
            decorate_dispatch_order(
                db,
                order,
                user=user if user_can_claim else None,
            )
        claimable_orders, non_claimable_orders = partition_dispatch_orders(orders)
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


@router.get("/reports")
async def order_reports_page(
    request: Request,
    order: int | None = None,
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
                "message": "你沒有員工報單頁面權限。",
                "user": user,
            },
            status_code=403,
        )

    ensure_order_report_tables()
    reports = list_reports_for_user(str(user.get("id") or ""))

    return templates.TemplateResponse(
        request=request,
        name="order_reports.html",
        context={
            "title": "報單系統",
            "user": user,
            "reports": reports,
            "counts": get_report_counts(reports),
            "focus_order_id": int(order) if order else None,
            "message": message,
            "error": error,
        },
    )


@router.post("/reports/{order_id}/submit")
async def submit_report(
    request: Request,
    order_id: int,
    streamed: str = Form(...),
    recording_saved: str = Form(...),
    named_worker_ids: list[str] | None = Form(default=None),
):
    user = require_dispatch_user(request)
    if not user:
        return redirect_to_reports(
            order=order_id,
            error="你沒有報單權限，或登入狀態已過期。",
        )

    try:
        submit_order_report(
            order_id=order_id,
            user=user,
            streamed=_form_bool(streamed),
            recording_saved=_form_bool(recording_saved),
            named_worker_ids=named_worker_ids or [],
        )
    except ValueError as exc:
        return redirect_to_reports(order=order_id, error=str(exc))

    return redirect_to_reports(order=order_id, message="報單已送出客服審核。")


@router.get("/reports/review")
async def order_report_review_page(
    request: Request,
    status: str = "open",
    order_id: int | None = None,
    message: str | None = None,
    error: str | None = None,
):
    user = require_report_reviewer(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "報單審核只開放客服與總管。",
                "user": get_current_user(request),
            },
            status_code=403,
        )

    ensure_order_report_tables()
    reports = list_reports_for_review(
        status_filter=status,
        order_id=order_id,
    )
    all_reports = list_reports_for_review(status_filter="all")

    return templates.TemplateResponse(
        request=request,
        name="order_report_review.html",
        context={
            "title": "報單審核",
            "user": user,
            "reports": reports,
            "counts": get_report_counts(all_reports),
            "current_status": status,
            "focus_order_id": int(order_id) if order_id else None,
            "message": message,
            "error": error,
        },
    )


@router.post("/reports/review/{order_id}/action")
async def review_report_action(
    request: Request,
    order_id: int,
    action: str = Form(...),
    review_note: str | None = Form(default=None),
    streamed: str | None = Form(default=None),
    recording_saved: str | None = Form(default=None),
    named_worker_ids: list[str] | None = Form(default=None),
):
    user = require_report_reviewer(request)
    if not user:
        return redirect_to_report_review(
            order_id=order_id,
            error="你沒有報單審核權限，或登入狀態已過期。",
        )

    try:
        result_message = review_order_report(
            order_id=order_id,
            support_user=user,
            action=action,
            note=review_note,
            streamed=(
                _form_bool(streamed)
                if streamed is not None
                else None
            ),
            recording_saved=(
                _form_bool(recording_saved)
                if recording_saved is not None
                else None
            ),
            named_worker_ids=(
                named_worker_ids
                if action == "approve"
                else None
            ),
        )
    except ValueError as exc:
        return redirect_to_report_review(
            order_id=order_id,
            error=str(exc),
        )

    return redirect_to_report_review(
        order_id=order_id,
        message=result_message,
    )


@router.post("/reports/review/{order_id}/remind")
async def remind_report_workers(request: Request, order_id: int):
    user = require_report_reviewer(request)
    if not user:
        return redirect_to_report_review(
            order_id=order_id,
            error="你沒有報單提醒權限，或登入狀態已過期。",
        )

    try:
        result = await run_in_threadpool(
            send_manual_report_reminder,
            order_id,
            user,
        )
    except ValueError as exc:
        return redirect_to_report_review(order_id=order_id, error=str(exc))
    except Exception as exc:
        return redirect_to_report_review(
            order_id=order_id,
            error=f"提醒失敗：{type(exc).__name__}",
        )

    return redirect_to_report_review(
        order_id=order_id,
        message=(
            f"已私訊 {int(result.get('sent', 0))} 位接單人員；"
            f"失敗 {int(result.get('failed', 0))} 位。"
        ),
    )


@router.get("/reports/status")
async def report_status_api(
    request: Request,
    order_ids: str = "",
):
    user = require_report_reviewer(request)
    if not user:
        return JSONResponse(
            {"error": "forbidden"},
            status_code=403,
        )

    parsed_ids: list[int] = []
    for raw in str(order_ids or "").split(","):
        try:
            value = int(raw.strip())
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in parsed_ids:
            parsed_ids.append(value)
        if len(parsed_ids) >= 100:
            break

    return JSONResponse(
        {"reports": get_report_status_map(parsed_ids)}
    )
