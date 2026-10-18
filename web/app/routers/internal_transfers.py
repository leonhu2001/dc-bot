from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.discord_service import get_dashboard_access, get_member_role_ids
from web.app.services.internal_transfers import (
    cancel_internal_transfer,
    create_internal_transfer,
    get_available_unpaid_balance,
    list_internal_employees,
    list_internal_transfers,
    review_internal_transfer,
)
from web.app.services.internal_wallet_transfers import (
    SELF_WALLET_DESTINATION,
    create_internal_wallet_transfer,
    is_internal_wallet_transfer,
    review_internal_wallet_transfer,
)


router = APIRouter(tags=["employee-internal-transfers"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def _redirect(*, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = str(message)
    if error:
        params["error"] = str(error)
    suffix = "?" + urlencode(params) if params else ""
    return RedirectResponse(f"/employee/internal-transfers{suffix}", status_code=303)


def _display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("id")
        or "未知人員"
    )


async def _refresh_employee_user(request: Request) -> dict | None:
    user = request.session.get("user")
    if not user:
        return None

    discord_id = str(user.get("id") or user.get("discord_id") or "").strip()
    if not discord_id:
        return None

    try:
        role_ids = await run_in_threadpool(get_member_role_ids, discord_id)
        access = get_dashboard_access(role_ids)
    except Exception:
        # 牽涉薪資的操作不能沿用過期權限。
        return None

    refreshed = dict(user)
    is_manager = bool(access.get("is_manager") or access.get("is_admin"))
    is_customer_service = bool(access.get("is_customer_service"))
    is_worker = bool(access.get("is_worker"))
    is_companion = bool(access.get("is_companion"))
    refreshed.update(
        {
            "id": discord_id,
            "role_ids": list(role_ids),
            "is_manager": is_manager,
            "is_customer_service": is_customer_service,
            "is_admin": bool(is_manager or is_customer_service),
            "is_worker": is_worker,
            "is_companion": is_companion,
            "is_employee": bool(
                is_manager or is_customer_service or is_worker or is_companion
            ),
        }
    )
    request.session["user"] = refreshed
    return refreshed if refreshed["is_employee"] else None


def _is_reviewer(user: dict) -> bool:
    return bool(user.get("is_customer_service") or user.get("is_manager"))


@router.get("/employee/internal-transfers")
async def internal_transfer_page(request: Request):
    user = await _refresh_employee_user(request)
    if not user:
        if request.session.get("user"):
            return RedirectResponse("/no-access", status_code=303)
        return RedirectResponse(
            "/auth/discord/login?next=/employee/internal-transfers",
            status_code=303,
        )

    user_id = str(user.get("id") or "")
    reviewer = _is_reviewer(user)
    employees = list_internal_employees(include_balances=reviewer)
    rows = list_internal_transfers(user_id, include_all=reviewer)

    pending_reviews = (
        [row for row in rows if row.get("status") == "pending"]
        if reviewer
        else []
    )
    my_rows = [
        row
        for row in rows
        if not reviewer
        or user_id
        in {
            str(row.get("from_employee_discord_id") or ""),
            str(row.get("to_employee_discord_id") or ""),
            str(row.get("created_by_discord_id") or ""),
        }
    ]

    return templates.TemplateResponse(
        request=request,
        name="employee_internal_transfers.html",
        context={
            "title": "內部轉帳｜魔丸娛樂",
            "user": user,
            "is_reviewer": reviewer,
            "employees": employees,
            "available": get_available_unpaid_balance(user_id),
            "pending_reviews": pending_reviews,
            "transfer_rows": my_rows,
            "wallet_destination_value": SELF_WALLET_DESTINATION,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/employee/internal-transfers")
async def create_transfer(request: Request):
    user = await _refresh_employee_user(request)
    if not user:
        return RedirectResponse("/no-access", status_code=303)

    reviewer = _is_reviewer(user)
    form = await request.form()
    actor_id = str(user.get("id") or "")
    from_id = (
        str(form.get("from_employee_discord_id") or "").strip()
        if reviewer
        else actor_id
    )
    to_id = str(form.get("to_employee_discord_id") or "").strip()

    try:
        common_args = {
            "actor_discord_id": actor_id,
            "actor_display_name": _display_name(user),
            "from_employee_discord_id": from_id,
            "amount": int(str(form.get("amount") or "0")),
            "reason": str(form.get("reason") or ""),
            "actor_is_customer_service": bool(user.get("is_customer_service")),
            "actor_is_manager": bool(user.get("is_manager")),
        }
        if to_id == SELF_WALLET_DESTINATION:
            result = create_internal_wallet_transfer(**common_args)
        else:
            result = create_internal_transfer(
                **common_args,
                to_employee_discord_id=to_id,
            )
    except (TypeError, ValueError) as exc:
        return _redirect(error=str(exc))

    if result.get("auto_approved"):
        return _redirect(
            message=(
                f"內部轉帳 #{result['id']} 已直接生效："
                f"{result['from_name']} → {result['to_name']} {result['amount']}T。"
            )
        )
    return _redirect(message=f"內部轉帳 #{result['id']} 已送出，等待客服審核。")


@router.post("/employee/internal-transfers/{transfer_id}/approve")
async def approve_transfer(transfer_id: int, request: Request):
    user = await _refresh_employee_user(request)
    if not user:
        return RedirectResponse("/no-access", status_code=303)

    form = await request.form()
    reviewer_args = {
        "transfer_id": transfer_id,
        "reviewer_discord_id": str(user.get("id") or ""),
        "reviewer_display_name": _display_name(user),
        "reviewer_is_customer_service": bool(user.get("is_customer_service")),
        "reviewer_is_manager": bool(user.get("is_manager")),
        "review_note": str(form.get("review_note") or ""),
    }
    try:
        if is_internal_wallet_transfer(transfer_id):
            review_internal_wallet_transfer(**reviewer_args, approve=True)
        else:
            review_internal_transfer(**reviewer_args, approve=True)
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"內部轉帳 #{transfer_id} 已核准，薪資調整已生效。")


@router.post("/employee/internal-transfers/{transfer_id}/reject")
async def reject_transfer(transfer_id: int, request: Request):
    user = await _refresh_employee_user(request)
    if not user:
        return RedirectResponse("/no-access", status_code=303)

    form = await request.form()
    reviewer_args = {
        "transfer_id": transfer_id,
        "reviewer_discord_id": str(user.get("id") or ""),
        "reviewer_display_name": _display_name(user),
        "reviewer_is_customer_service": bool(user.get("is_customer_service")),
        "reviewer_is_manager": bool(user.get("is_manager")),
        "review_note": str(form.get("review_note") or ""),
    }
    try:
        if is_internal_wallet_transfer(transfer_id):
            review_internal_wallet_transfer(**reviewer_args, approve=False)
        else:
            review_internal_transfer(**reviewer_args, approve=False)
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"內部轉帳 #{transfer_id} 已拒絕。")


@router.post("/employee/internal-transfers/{transfer_id}/cancel")
async def cancel_transfer(transfer_id: int, request: Request):
    user = await _refresh_employee_user(request)
    if not user:
        return RedirectResponse("/no-access", status_code=303)

    try:
        cancel_internal_transfer(
            transfer_id=transfer_id,
            actor_discord_id=str(user.get("id") or ""),
            actor_is_customer_service=bool(user.get("is_customer_service")),
            actor_is_manager=bool(user.get("is_manager")),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(message=f"內部轉帳 #{transfer_id} 已取消。")


@router.get("/employee/payout-splits")
async def legacy_payout_split_redirect():
    return RedirectResponse("/employee/internal-transfers", status_code=303)