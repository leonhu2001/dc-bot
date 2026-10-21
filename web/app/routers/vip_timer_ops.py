from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.vip_timer_ops import (
    clear_end_request,
    correct_segment,
    ensure_vip_timer_ops_tables,
    get_timer_detail,
    list_open_timer_operations,
    open_dispute,
    recalculate_pending_settlement,
    resolve_dispute,
)
from services.vip_timer_pause_confirmation import clear_pause_request
from web.app.routers.admin_common import require_admin_user
from web.app.services.customer_portal import get_customer_order
from web.app.config import config


router = APIRouter(tags=["vip-timer-ops"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_user(request: Request) -> dict | None:
    return request.session.get("user")


def _duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小時 {minutes} 分"
    if minutes:
        return f"{minutes} 分"
    return f"{seconds} 秒"


def _timer_redirect(order_id: int, *, message: str | None = None, error: str | None = None):
    from urllib.parse import urlencode

    params = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    url = f"/admin/vip-timers/{int(order_id)}"
    if params:
        url += "?" + urlencode(params)
    return RedirectResponse(url=url, status_code=303)


@router.get("/admin/vip-timers")
async def admin_vip_timers(request: Request):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    ensure_vip_timer_ops_tables()
    rows = list_open_timer_operations()
    for row in rows:
        row["age_text"] = _duration(int(row.get("age_seconds") or 0))
        row["pending_age_text"] = _duration(int(row.get("pending_age_seconds") or 0))
        row["needs_payment_attention"] = int(row.get("pending_age_seconds") or 0) >= 24 * 3600
    return templates.TemplateResponse(
        request=request,
        name="admin_vip_timers.html",
        context={
            "title": "VIP 自由計時｜客服後台",
            "user": user,
            "rows": rows,
        },
    )


@router.get("/admin/vip-timers/{order_id}")
async def admin_vip_timer_detail(
    order_id: int,
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    detail = get_timer_detail(int(order_id))
    if detail is None:
        return RedirectResponse(url="/admin/vip-timers?error=找不到自由計時單", status_code=303)
    detail["live_text"] = _duration(int(detail.get("live_seconds") or 0))
    detail["pending_age_text"] = _duration(int(detail.get("pending_age_seconds") or 0))
    for segment in detail.get("segments") or []:
        segment["duration_text"] = _duration(int(segment.get("billable_seconds") or 0))
        try:
            import json
            segment["staff_ids_text"] = ", ".join(json.loads(str(segment.get("staff_ids_json") or "[]")))
        except Exception:
            segment["staff_ids_text"] = ""
    return templates.TemplateResponse(
        request=request,
        name="admin_vip_timer_detail.html",
        context={
            "title": f"VIP-TIMER WEB-{int(order_id)}｜客服後台",
            "user": user,
            "detail": detail,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/vip-timers/{order_id}/pause")
async def admin_vip_timer_force_pause(order_id: int, request: Request):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    from services import vip_timer as timer

    session = timer.get_session(int(order_id)) or {}
    if str(session.get("status") or "") != "running":
        return _timer_redirect(order_id, error="目前不是計時中狀態。")
    try:
        timer.pause_timer(int(order_id), str(user.get("id") or ""))
        clear_pause_request(int(order_id), actor_id=user.get("id"), reason="admin_correction_pause")
        clear_end_request(int(order_id), actor_id=user.get("id"), reason="admin_correction_pause")
    except ValueError as exc:
        return _timer_redirect(order_id, error=str(exc))
    return _timer_redirect(order_id, message="已由客服強制暫停，可開始修正計時紀錄。")


@router.post("/admin/vip-timers/{order_id}/segments/{segment_id}/correct")
async def admin_vip_timer_correct_segment(
    order_id: int,
    segment_id: int,
    request: Request,
    billable_seconds: int = Form(...),
    hourly_rate: int = Form(...),
    staff_ids: str = Form(default=""),
    started_at: str = Form(default=""),
    ended_at: str = Form(default=""),
    reason: str = Form(...),
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    staff = [part.strip() for part in str(staff_ids or "").replace("，", ",").split(",") if part.strip()]
    try:
        result = correct_segment(
            int(order_id),
            int(segment_id),
            actor_id=user.get("id"),
            reason=reason,
            billable_seconds=int(billable_seconds),
            hourly_rate=int(hourly_rate),
            staff_ids=staff,
            started_at=started_at or None,
            ended_at=ended_at or None,
        )
    except ValueError as exc:
        return _timer_redirect(order_id, error=str(exc))
    message = "計時區段已修正並留下稽核紀錄。"
    if isinstance(result, dict) and "customer_pay" in result:
        message += f" 待付款金額已重算為 {int(result['customer_pay']):,}T。"
    return _timer_redirect(order_id, message=message)


@router.post("/admin/vip-timers/{order_id}/recalculate")
async def admin_vip_timer_recalculate(order_id: int, request: Request, reason: str = Form(default="客服重新結算")):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        result = recalculate_pending_settlement(
            int(order_id), actor_id=user.get("id"), reason=reason
        )
    except ValueError as exc:
        return _timer_redirect(order_id, error=str(exc))
    return _timer_redirect(
        order_id,
        message=f"已依開單 VIP 快照重新結算：原始 {result['gross']:,}T／應付 {result['customer_pay']:,}T。",
    )


@router.post("/admin/vip-timers/{order_id}/disputes")
async def admin_vip_timer_open_dispute(order_id: int, request: Request, reason: str = Form(...)):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        dispute_id = open_dispute(int(order_id), actor_id=user.get("id"), reason=reason)
    except ValueError as exc:
        return _timer_redirect(order_id, error=str(exc))
    return _timer_redirect(order_id, message=f"已建立爭議紀錄 #{dispute_id}。")


@router.post("/admin/vip-timers/{order_id}/disputes/{dispute_id}/resolve")
async def admin_vip_timer_resolve_dispute(
    order_id: int,
    dispute_id: int,
    request: Request,
    resolution: str = Form(...),
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        resolve_dispute(
            int(order_id), int(dispute_id), actor_id=user.get("id"), resolution=resolution
        )
    except ValueError as exc:
        return _timer_redirect(order_id, error=str(exc))
    return _timer_redirect(order_id, message=f"爭議 #{int(dispute_id)} 已結案。")


def _member_timer_access(request: Request, order_id: int):
    user = _current_user(request)
    if not user:
        return None, None
    customer_id = str(user.get("id") or "").strip()
    order = get_customer_order(customer_id, int(order_id), guild_id=config.DISCORD_GUILD_ID)
    if order is None:
        return user, None
    detail = get_timer_detail(int(order_id))
    if detail is None:
        return user, None
    if str((detail.get("session") or {}).get("customer_discord_id") or "") != customer_id:
        return user, None
    return user, detail


@router.get("/me/orders/{order_id}/timer")
async def member_vip_timer_live(order_id: int, request: Request):
    user, detail = _member_timer_access(request, int(order_id))
    if user is None:
        return RedirectResponse(
            url=f"/auth/discord/login?next=/me/orders/{int(order_id)}/timer",
            status_code=303,
        )
    if detail is None:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={"title": "找不到自由計時單", "message": "這筆自由計時單不存在，或不屬於目前登入的 Discord 帳號。", "user": user},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="member_vip_timer_live.html",
        context={
            "title": f"VIP 自由計時 WEB-{int(order_id)}｜魔丸娛樂",
            "user": user,
            "order_id": int(order_id),
            "detail": detail,
        },
    )


@router.get("/me/orders/{order_id}/timer/status")
async def member_vip_timer_status(order_id: int, request: Request):
    user, detail = _member_timer_access(request, int(order_id))
    if user is None:
        return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
    if detail is None:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    session = detail.get("session") or {}
    segments = []
    from services.vip_timer_ops import _segment_effective_seconds
    for row in detail.get("segments") or []:
        segments.append({
            "seq": int(row.get("seq") or 0),
            "category_label": str(row.get("category_label") or ""),
            "rule_label": str(row.get("rule_label") or ""),
            "hourly_rate": int(row.get("hourly_rate") or 0),
            "seconds": _segment_effective_seconds(row, str(session.get("status") or "")),
            "started_at": str(row.get("started_at") or ""),
            "ended_at": str(row.get("ended_at") or ""),
        })
    return JSONResponse({
        "ok": True,
        "order_id": int(order_id),
        "status": str(session.get("status") or ""),
        "current_rule_label": str(session.get("current_rule_label") or ""),
        "current_category_label": str(session.get("current_category_label") or ""),
        "current_hourly_rate": int(session.get("current_hourly_rate") or 0),
        "live_seconds": int(detail.get("live_seconds") or 0),
        "gross_preview": int(detail.get("gross_preview") or 0),
        "customer_preview": int(detail.get("customer_preview") or 0),
        "final_amount": int(session.get("final_amount") or 0),
        "vip_name": str(detail.get("vip_name_snapshot") or ""),
        "vip_discount_pay_rate": int(detail.get("vip_discount_pay_rate_snapshot") or 100),
        "pending_age_seconds": int(detail.get("pending_age_seconds") or 0),
        "end_confirmation_pending": bool(detail.get("end_request")),
        "segments": segments,
    }, headers={"Cache-Control": "no-store"})


__all__ = ["router"]
