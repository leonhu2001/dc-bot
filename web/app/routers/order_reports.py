from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web.app.services.dispatch_support import can_manage_dispatch_orders
from web.app.services.order_reporting import (
    REPORT_STATUS_APPROVED,
    REPORT_STATUS_CHANGES_REQUESTED,
    REPORT_STATUS_MISSING,
    REPORT_STATUS_PENDING,
    count_pending_review_reports,
    ensure_order_reporting_tables,
    get_report_detail_for_support,
    get_report_detail_for_worker,
    get_report_statuses,
    list_reports_for_review,
    list_reports_for_user,
    order_report_reminder_loop,
    reset_order_report_reminders,
    review_order_report,
    send_pending_order_report_reminders,
    submit_order_report,
)


router = APIRouter(tags=["order-reports"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_reminder_task: asyncio.Task | None = None


STATUS_LABELS = {
    REPORT_STATUS_MISSING: "未報單",
    REPORT_STATUS_PENDING: "待審核",
    REPORT_STATUS_CHANGES_REQUESTED: "需修改",
    REPORT_STATUS_APPROVED: "已報單",
}


def _current_user(request: Request) -> dict | None:
    return request.session.get("user")


def _display_name(user: dict | None) -> str:
    user = user or {}
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


def _redirect(path: str, **params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    if query:
        path = f"{path}?{urlencode(query)}"
    return RedirectResponse(url=path, status_code=303)


def _no_access(request: Request, *, title: str, message: str, status_code: int):
    return templates.TemplateResponse(
        request=request,
        name="no_access.html",
        context={
            "title": title,
            "message": message,
            "user": _current_user(request),
        },
        status_code=status_code,
    )


def _parse_bool(form, key: str) -> bool | None:
    if key not in form:
        return None
    value = str(form.get(key) or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_named_map(form, workers: list[dict]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for worker in workers:
        worker_id = str(worker.get("worker_discord_id") or "").strip()
        if not worker_id:
            continue
        key = f"named_{worker_id}"
        if key not in form:
            continue
        value = str(form.get(key) or "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            result[worker_id] = True
        elif value in {"0", "false", "no", "off"}:
            result[worker_id] = False
    return result


def _parse_worker_stream_maps(
    form,
    workers: list[dict],
) -> tuple[dict[str, bool], dict[str, str]]:
    streamed_by_worker: dict[str, bool] = {}
    stream_url_by_worker: dict[str, str] = {}
    for worker in workers:
        worker_id = str(worker.get("worker_discord_id") or "").strip()
        if not worker_id:
            continue
        streamed_key = f"streamed_{worker_id}"
        if streamed_key in form:
            value = str(form.get(streamed_key) or "").strip().lower()
            if value in {"1", "true", "yes", "on"}:
                streamed_by_worker[worker_id] = True
            elif value in {"0", "false", "no", "off"}:
                streamed_by_worker[worker_id] = False
        stream_url_by_worker[worker_id] = str(
            form.get(f"stream_url_{worker_id}") or ""
        ).strip()
    return streamed_by_worker, stream_url_by_worker


@router.on_event("startup")
async def _order_report_startup() -> None:
    global _reminder_task
    ensure_order_reporting_tables()
    if _reminder_task is None or _reminder_task.done():
        _reminder_task = asyncio.create_task(
            order_report_reminder_loop(),
            name="order-report-reminder-loop",
        )


@router.on_event("shutdown")
async def _order_report_shutdown() -> None:
    global _reminder_task
    if _reminder_task is not None and not _reminder_task.done():
        _reminder_task.cancel()
        try:
            await _reminder_task
        except asyncio.CancelledError:
            pass
    _reminder_task = None


@router.get("/dispatch/reports")
async def order_report_index(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    message: str | None = None,
    error: str | None = None,
):
    user = _current_user(request)
    if not user:
        return _no_access(
            request,
            title="請先登入",
            message="請先使用 Discord 登入後再查看報單系統。",
            status_code=401,
        )

    reports = list_reports_for_user(
        str(user.get("id") or ""),
        status_filter=status,
        keyword=q,
    )
    support_can_manage = can_manage_dispatch_orders(user)
    return templates.TemplateResponse(
        request=request,
        name="order_reports.html",
        context={
            "title": "報單系統",
            "user": user,
            "reports": reports,
            "status_filter": status or "",
            "q": q or "",
            "status_labels": STATUS_LABELS,
            "support_can_manage": support_can_manage,
            "pending_report_review_count": (
                count_pending_review_reports()
                if support_can_manage
                else 0
            ),
            "message": message,
            "error": error,
        },
    )


# Static review/status paths are declared before /dispatch/reports/{order_id}
# so Starlette never treats words such as "review" as an order ID.
@router.get("/dispatch/reports/statuses.json")
async def order_report_statuses_api(request: Request, order_ids: str = ""):
    user = _current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    parsed_ids: list[int] = []
    for token in str(order_ids or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if value > 0:
            parsed_ids.append(value)
        if len(parsed_ids) >= 300:
            break

    return JSONResponse({
        "statuses": {
            str(order_id): status
            for order_id, status in get_report_statuses(parsed_ids).items()
        },
        "labels": STATUS_LABELS,
    })


@router.get("/dispatch/reports/review-count.json")
async def order_report_review_count_api(request: Request):
    user = _current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return JSONResponse({"count": 0}, status_code=403)
    return JSONResponse({"count": count_pending_review_reports()})


@router.get("/dispatch/reports/review")
async def order_report_review_index(
    request: Request,
    status: str | None = "actionable",
    q: str | None = None,
    message: str | None = None,
    error: str | None = None,
):
    user = _current_user(request)
    if not user:
        return _no_access(
            request,
            title="請先登入",
            message="請先使用 Discord 登入。",
            status_code=401,
        )
    if not can_manage_dispatch_orders(user):
        return _no_access(
            request,
            title="沒有權限",
            message="報單審核僅限客服、總管或管理員使用。",
            status_code=403,
        )

    reports = list_reports_for_review(
        status_filter=status,
        keyword=q,
    )
    return templates.TemplateResponse(
        request=request,
        name="order_report_review.html",
        context={
            "title": "報單審核",
            "user": user,
            "reports": reports,
            "status_filter": status or "actionable",
            "q": q or "",
            "status_labels": STATUS_LABELS,
            "support_can_manage": True,
            "pending_report_review_count": count_pending_review_reports(),
            "message": message,
            "error": error,
        },
    )


@router.get("/dispatch/reports/review/{order_id}")
async def order_report_review_detail(
    request: Request,
    order_id: int,
    message: str | None = None,
    error: str | None = None,
):
    user = _current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return _no_access(
            request,
            title="沒有權限",
            message="報單審核僅限客服、總管或管理員使用。",
            status_code=403,
        )

    detail = get_report_detail_for_support(order_id)
    if detail is None:
        return _no_access(
            request,
            title="找不到報單",
            message="找不到這張已結單訂單。",
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="order_report_review_detail.html",
        context={
            "title": "報單審核詳情",
            "user": user,
            "detail": detail,
            "workers": detail.get("workers", []),
            "status_labels": STATUS_LABELS,
            "support_can_manage": True,
            "pending_report_review_count": count_pending_review_reports(),
            "message": message,
            "error": error,
        },
    )


@router.post("/dispatch/reports/review/{order_id}")
async def order_report_review_submit(request: Request, order_id: int):
    user = _current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return _redirect(
            f"/dispatch/reports/review/{order_id}",
            error="你沒有報單審核權限。",
        )

    detail = get_report_detail_for_support(order_id)
    if detail is None:
        return _redirect("/dispatch/reports/review", error="找不到這張訂單。")

    form = await request.form()
    action = str(form.get("action") or "").strip()
    try:
        if action == REPORT_STATUS_CHANGES_REQUESTED:
            review_order_report(
                order_id=order_id,
                admin_user=user,
                action=REPORT_STATUS_CHANGES_REQUESTED,
                review_note=str(form.get("review_note") or ""),
            )
            return _redirect(
                "/dispatch/reports/review",
                message=f"已退回 {detail.get('bot_order_no') or ('WEB-' + str(order_id))}，等待接單人員修改。",
            )

        if action != REPORT_STATUS_APPROVED:
            raise ValueError("請選擇審核操作。")

        recording_saved = _parse_bool(form, "recording_saved")
        named_map = _parse_named_map(form, detail.get("workers", []))
        streamed_map, stream_url_map = _parse_worker_stream_maps(
            form,
            detail.get("workers", []),
        )
        review_order_report(
            order_id=order_id,
            admin_user=user,
            action=REPORT_STATUS_APPROVED,
            review_note=str(form.get("review_note") or ""),
            recording_saved=recording_saved,
            recording_holder=str(form.get("recording_holder") or ""),
            note=str(form.get("note") or ""),
            named_bonus_by_worker=named_map,
            streamed_by_worker=streamed_map,
            stream_url_by_worker=stream_url_map,
        )
    except ValueError as exc:
        return _redirect(
            f"/dispatch/reports/review/{order_id}",
            error=str(exc),
        )

    return _redirect(
        "/dispatch/reports/review",
        message=f"{detail.get('bot_order_no') or ('WEB-' + str(order_id))} 報單已通過。",
    )


@router.post("/dispatch/reports/review/{order_id}/remind")
async def order_report_manual_remind(request: Request, order_id: int):
    user = _current_user(request)
    if not user or not can_manage_dispatch_orders(user):
        return _redirect("/dispatch/reports/review", error="你沒有提醒權限。")

    queued = reset_order_report_reminders(order_id)
    if queued <= 0:
        return _redirect(
            f"/dispatch/reports/review/{order_id}",
            error="這張訂單目前不是未報單狀態，或沒有可提醒的接單人員。",
        )

    result = await send_pending_order_report_reminders(
        limit=max(queued, 1),
        order_id=order_id,
    )
    if result.get("sent", 0) > 0:
        message = f"已重新私訊提醒 {result['sent']} 位接單人員。"
        if result.get("failed", 0):
            message += f"另有 {result['failed']} 位私訊失敗，可請客服人工提醒。"
        return _redirect(
            f"/dispatch/reports/review/{order_id}",
            message=message,
        )

    return _redirect(
        f"/dispatch/reports/review/{order_id}",
        error="私訊提醒沒有成功送出，可能是對方關閉私訊；網站仍可正常填報。",
    )


@router.get("/dispatch/reports/{order_id}")
async def order_report_detail(
    request: Request,
    order_id: int,
    message: str | None = None,
    error: str | None = None,
):
    user = _current_user(request)
    if not user:
        return _no_access(
            request,
            title="請先登入",
            message="請先使用 Discord 登入後再查看報單。",
            status_code=401,
        )

    detail = get_report_detail_for_worker(
        order_id,
        str(user.get("id") or ""),
    )
    if detail is None:
        return _no_access(
            request,
            title="沒有權限",
            message="你只能查看自己實際參與過的已結單訂單。",
            status_code=403,
        )

    readonly = bool(
        detail.get("is_legacy")
        or detail.get("report_status")
        in {REPORT_STATUS_PENDING, REPORT_STATUS_APPROVED}
    )
    return templates.TemplateResponse(
        request=request,
        name="order_report_detail.html",
        context={
            "title": "填寫報單",
            "user": user,
            "detail": detail,
            "workers": detail.get("workers", []),
            "readonly": readonly,
            "status_labels": STATUS_LABELS,
            "support_can_manage": can_manage_dispatch_orders(user),
            "pending_report_review_count": (
                count_pending_review_reports()
                if can_manage_dispatch_orders(user)
                else 0
            ),
            "message": message,
            "error": error,
        },
    )


@router.post("/dispatch/reports/{order_id}")
async def order_report_submit(request: Request, order_id: int):
    user = _current_user(request)
    if not user:
        return _redirect(
            f"/dispatch/reports/{order_id}",
            error="登入狀態已失效，請重新登入。",
        )

    detail = get_report_detail_for_worker(
        order_id,
        str(user.get("id") or ""),
    )
    if detail is None:
        return _redirect(
            "/dispatch/reports",
            error="你沒有這張訂單的報單權限。",
        )

    form = await request.form()
    recording_saved = _parse_bool(form, "recording_saved")
    if recording_saved is None:
        return _redirect(
            f"/dispatch/reports/{order_id}",
            error="請確認是否保留錄影。",
        )

    named_map = _parse_named_map(form, detail.get("workers", []))
    streamed_map, stream_url_map = _parse_worker_stream_maps(
        form,
        detail.get("workers", []),
    )
    try:
        submit_order_report(
            order_id=order_id,
            user=user,
            recording_saved=recording_saved,
            recording_holder=str(form.get("recording_holder") or ""),
            note=str(form.get("note") or ""),
            named_bonus_by_worker=named_map,
            streamed_by_worker=streamed_map,
            stream_url_by_worker=stream_url_map,
        )
    except ValueError as exc:
        return _redirect(
            f"/dispatch/reports/{order_id}",
            error=str(exc),
        )

    return _redirect(
        "/dispatch/reports",
        message=(
            f"{detail.get('bot_order_no') or ('WEB-' + str(order_id))} 已送出審核。"
            "同單其他接單人員不用重複填寫。"
        ),
    )
