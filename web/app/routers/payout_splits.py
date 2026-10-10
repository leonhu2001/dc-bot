from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web.app.services.payout_splits import (
    cancel_payout_split,
    create_payout_split,
    decide_payout_split,
    list_eligible_orders,
    list_payout_splits,
)


router = APIRouter(tags=["employee-payout-splits"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def _current_user(request: Request) -> dict | None:
    return request.session.get("user")


def _is_employee(user: dict | None) -> bool:
    if not user:
        return False
    return bool(
        user.get("is_employee")
        or user.get("is_worker")
        or user.get("is_companion")
        or user.get("is_customer_service")
        or user.get("is_manager")
        or user.get("is_admin")
    )


def _display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知人員"
    )


def _redirect(*, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = str(message)
    if error:
        params["error"] = str(error)
    suffix = "?" + urlencode(params) if params else ""
    return RedirectResponse(f"/employee/payout-splits{suffix}", status_code=303)


def _require_employee(request: Request) -> dict | RedirectResponse:
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not _is_employee(user):
        return RedirectResponse("/no-access", status_code=303)
    return user


@router.get("/employee/payout-splits")
async def employee_payout_splits(request: Request):
    user_or_response = _require_employee(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response

    user = user_or_response
    user_id = str(user.get("id") or "")
    is_manager = bool(user.get("is_manager"))
    split_rows = list_payout_splits(user_id, include_all=is_manager)

    pending_incoming = [
        row for row in split_rows
        if row.get("status") == "pending" and row.get("can_approve")
    ]
    pending_outgoing = [
        row for row in split_rows
        if row.get("status") == "pending"
        and str(row.get("from_worker_discord_id") or "") == user_id
    ]
    history_rows = [row for row in split_rows if row.get("status") != "pending"]

    return templates.TemplateResponse(
        request=request,
        name="employee_payout_splits.html",
        context={
            "title": "訂單分帳｜魔丸娛樂",
            "user": user,
            "is_manager": is_manager,
            "eligible_orders": list_eligible_orders(user_id),
            "pending_incoming": pending_incoming,
            "pending_outgoing": pending_outgoing,
            "history_rows": history_rows,
            "all_split_rows": split_rows,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/employee/payout-splits")
async def create_employee_payout_split(request: Request):
    user_or_response = _require_employee(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    user = user_or_response

    form = await request.form()
    try:
        order_id = int(str(form.get("order_id") or "0"))
        amount = int(str(form.get("amount") or "0"))
        hours_raw = str(form.get("hours") or "").strip()
        hours = float(hours_raw) if hours_raw else None
        split_id = create_payout_split(
            order_id=order_id,
            from_worker_discord_id=str(user.get("id") or ""),
            from_worker_display_name=_display_name(user),
            to_worker_discord_id=str(form.get("to_worker_discord_id") or ""),
            amount=amount,
            hours=hours,
            reason=str(form.get("reason") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"分帳 #{split_id} 已送出，等待對方確認。")


@router.post("/employee/payout-splits/{split_id}/approve")
async def approve_employee_payout_split(split_id: int, request: Request):
    user_or_response = _require_employee(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    user = user_or_response

    form = await request.form()
    try:
        decide_payout_split(
            split_id=split_id,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            approve=True,
            is_manager=bool(user.get("is_manager")),
            decision_note=str(form.get("decision_note") or ""),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"分帳 #{split_id} 已確認，雙方薪資已更新。")


@router.post("/employee/payout-splits/{split_id}/reject")
async def reject_employee_payout_split(split_id: int, request: Request):
    user_or_response = _require_employee(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    user = user_or_response

    form = await request.form()
    try:
        decide_payout_split(
            split_id=split_id,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            approve=False,
            is_manager=bool(user.get("is_manager")),
            decision_note=str(form.get("decision_note") or ""),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"分帳 #{split_id} 已拒絕。")


@router.post("/employee/payout-splits/{split_id}/cancel")
async def cancel_employee_payout_split(split_id: int, request: Request):
    user_or_response = _require_employee(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    user = user_or_response

    try:
        cancel_payout_split(
            split_id=split_id,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            is_manager=bool(user.get("is_manager")),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"分帳 #{split_id} 已取消。")
