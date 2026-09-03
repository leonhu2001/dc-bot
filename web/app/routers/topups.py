from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.topups import (
    approve_topup_order,
    calculate_topup_preview,
    cancel_topup_order,
    create_topup_order,
    get_topup_order,
    list_customer_topups,
    list_topups_for_admin,
    reject_topup_order,
    submit_topup_payment,
    topup_status_label,
)
from web.app.routers.admin_staff import _mw4b2_admin_user as _admin_user
from web.app.services.site_data import get_member_summary

router = APIRouter(tags=["topups"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _user(request: Request) -> dict | None:
    return request.session.get("user")


def _display_name(user: dict) -> str:
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "老闆"
    )


def _decorate(order: dict) -> dict:
    item = dict(order)
    item["status_label"] = topup_status_label(item.get("status"))
    item["amount_text"] = f"{int(item.get('amount') or 0):,}T"
    item["rebate_amount_text"] = f"{int(item.get('rebate_amount') or 0):,}T"
    item["credited_amount_text"] = f"{int(item.get('credited_amount') or 0):,}T"
    return item


@router.get("/me/wallet", response_class=HTMLResponse)
async def member_wallet(request: Request):
    user = _user(request)
    if not user:
        return RedirectResponse("/auth/discord/login", status_code=303)

    customer_id = str(user.get("id") or "")
    member = get_member_summary(customer_id)
    topups = [_decorate(row) for row in list_customer_topups(customer_id, limit=30)]

    return templates.TemplateResponse(
        request=request,
        name="member_wallet.html",
        context={
            "title": "我的錢包｜魔丸娛樂",
            "page_name": "member_wallet",
            "user": user,
            "member": member,
            "topups": topups,
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@router.post("/me/wallet/topup")
async def member_wallet_topup_create(
    request: Request,
    amount: int = Form(...),
):
    user = _user(request)
    if not user:
        return RedirectResponse("/auth/discord/login", status_code=303)

    try:
        order = create_topup_order(
            customer_discord_id=str(user.get("id") or ""),
            customer_display_name=_display_name(user),
            amount=int(amount),
            source="web",
            payment_method="bank_transfer",
        )
    except ValueError as exc:
        return RedirectResponse(f"/me/wallet?error={str(exc)}", status_code=303)

    return RedirectResponse(f"/me/wallet/topup/{int(order['id'])}", status_code=303)


@router.get("/me/wallet/topup/{topup_id}", response_class=HTMLResponse)
async def member_wallet_topup_detail(request: Request, topup_id: int):
    user = _user(request)
    if not user:
        return RedirectResponse("/auth/discord/login", status_code=303)

    order = get_topup_order(topup_id)
    customer_id = str(user.get("id") or "")
    if not order or str(order.get("customer_discord_id")) != customer_id:
        return RedirectResponse("/me/wallet?error=找不到這筆儲值單", status_code=303)

    member = get_member_summary(customer_id)
    preview = calculate_topup_preview(member.get("total_spent", 0), int(order.get("amount") or 0))

    return templates.TemplateResponse(
        request=request,
        name="member_topup_detail.html",
        context={
            "title": "儲值明細｜魔丸娛樂",
            "page_name": "member_wallet",
            "user": user,
            "member": member,
            "topup": _decorate(order),
            "preview": preview,
            "status_label": topup_status_label(order.get("status")),
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@router.post("/me/wallet/topup/{topup_id}/submit")
async def member_wallet_topup_submit(
    request: Request,
    topup_id: int,
    bank_last5: str = Form(...),
    payment_note: str = Form(default=""),
):
    user = _user(request)
    if not user:
        return RedirectResponse("/auth/discord/login", status_code=303)
    try:
        submit_topup_payment(
            topup_id,
            customer_discord_id=str(user.get("id") or ""),
            bank_last5=bank_last5,
            payment_note=payment_note,
        )
    except ValueError as exc:
        return RedirectResponse(f"/me/wallet/topup/{topup_id}?error={str(exc)}", status_code=303)
    return RedirectResponse(f"/me/wallet/topup/{topup_id}?ok=付款資料已送出，等待客服審核", status_code=303)


@router.post("/me/wallet/topup/{topup_id}/cancel")
async def member_wallet_topup_cancel(request: Request, topup_id: int):
    user = _user(request)
    if not user:
        return RedirectResponse("/auth/discord/login", status_code=303)
    try:
        cancel_topup_order(topup_id, customer_discord_id=str(user.get("id") or ""))
    except ValueError as exc:
        return RedirectResponse(f"/me/wallet/topup/{topup_id}?error={str(exc)}", status_code=303)
    return RedirectResponse("/me/wallet?ok=儲值單已取消", status_code=303)


@router.get("/admin/topups", response_class=HTMLResponse)
async def admin_topups(request: Request, status: str | None = None):
    if not _admin_user(request):
        return RedirectResponse("/admin", status_code=303)
    rows = [_decorate(row) for row in list_topups_for_admin(status=status, limit=200)]
    return templates.TemplateResponse(
        request=request,
        name="admin_topups.html",
        context={
            "title": "儲值審核",
            "user": _user(request),
            "topups": rows,
            "status_filter": status or "",
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@router.post("/admin/topups/{topup_id}/approve")
async def admin_topup_approve(request: Request, topup_id: int):
    user = _user(request)
    if not _admin_user(request) or not user:
        return RedirectResponse("/admin", status_code=303)
    try:
        approve_topup_order(
            topup_id,
            operator_discord_id=str(user.get("id") or ""),
            operator_display_name=_display_name(user),
        )
    except ValueError as exc:
        return RedirectResponse(f"/admin/topups?error={str(exc)}", status_code=303)
    return RedirectResponse("/admin/topups?ok=已核准，Bot 將自動完成錢包與 VIP 入帳", status_code=303)


@router.post("/admin/topups/{topup_id}/reject")
async def admin_topup_reject(
    request: Request,
    topup_id: int,
    reason: str = Form(default=""),
):
    user = _user(request)
    if not _admin_user(request) or not user:
        return RedirectResponse("/admin", status_code=303)
    try:
        reject_topup_order(
            topup_id,
            operator_discord_id=str(user.get("id") or ""),
            reason=reason,
        )
    except ValueError as exc:
        return RedirectResponse(f"/admin/topups?error={str(exc)}", status_code=303)
    return RedirectResponse("/admin/topups?ok=儲值單已駁回", status_code=303)
