from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.payment_reviews import (
    approve_payment_review,
    list_payment_reviews,
    payment_review_status_label,
    reject_payment_review,
)
from services.topups import (
    approve_topup_order,
    list_topups_for_admin,
    reject_topup_order,
    topup_payment_method_label,
    topup_payment_reference_label,
    topup_status_label,
)
from web.app.routers.admin_staff import require_admin

router = APIRouter(tags=["payment_reviews"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

GUILD_ID = 1129474191226306672


def _display_name(user: dict) -> str:
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "客服"
    )


def _redirect_message(key: str, message: object) -> RedirectResponse:
    return RedirectResponse(
        f"/admin/payment-reviews?{key}={quote(str(message), safe='')}",
        status_code=303,
    )


def _normalize_status(value: str | None) -> str:
    value = str(value or "").strip().lower()
    return value if value in {"pending", "processing", "completed", "rejected", "failed"} else "all"


def _external_bucket(status: str) -> str:
    if status == "pending_review":
        return "pending"
    if status in {"approved_pending_apply", "rejected_pending_apply", "processing"}:
        return "processing"
    if status == "completed":
        return "completed"
    if status == "rejected":
        return "rejected"
    if status == "failed":
        return "failed"
    return "processing"


def _topup_bucket(status: str) -> str:
    if status in {"pending_review", "pending_payment"}:
        return "pending"
    if status in {"approved_pending_credit", "processing"}:
        return "processing"
    if status == "completed":
        return "completed"
    if status in {"rejected", "cancelled"}:
        return "rejected"
    return "processing"


def _decorate_external(row: dict) -> dict:
    review_type = str(row.get("review_type") or "")
    review_no = str(row.get("review_no") or f"PAY-{row.get('id')}")
    reference_id = int(row.get("reference_id") or 0)
    ticket_channel_id = str(row.get("ticket_channel_id") or "").strip()

    if review_type == "tip":
        type_label = "🍗 雞腿"
        reference_label = f"TIP-{reference_id}"
    else:
        type_label = "點單"
        order_id = int(row.get("order_id") or reference_id or 0)
        reference_label = f"WEB-{order_id}" if order_id else review_no

    status = str(row.get("status") or "")
    return {
        "source": "external",
        "id": int(row.get("id") or 0),
        "review_no": review_no,
        "type_label": type_label,
        "reference_label": reference_label,
        "customer_name": str(row.get("customer_display_name") or row.get("customer_discord_id") or "—"),
        "customer_id": str(row.get("customer_discord_id") or ""),
        "amount": int(row.get("amount") or 0),
        "payment_method": str(row.get("payment_method") or "—"),
        "payment_reference_label": "付款截圖",
        "payment_reference_display": "請至原票口核對",
        "ticket_channel_id": ticket_channel_id,
        "ticket_url": (
            f"https://discord.com/channels/{GUILD_ID}/{ticket_channel_id}"
            if ticket_channel_id
            else ""
        ),
        "status": status,
        "status_label": payment_review_status_label(status),
        "status_bucket": _external_bucket(status),
        "submitted_at": str(row.get("submitted_at") or row.get("created_at") or ""),
        "rejected_reason": str(row.get("rejected_reason") or ""),
        "last_error": str(row.get("last_error") or ""),
        "actionable": status == "pending_review",
    }


def _decorate_topup(row: dict) -> dict:
    status = str(row.get("status") or "")
    payment_method = str(row.get("payment_method") or "bank_transfer")
    payment_reference = str(
        row.get("payment_reference")
        or row.get("bank_last5")
        or "—"
    )
    return {
        "source": "topup",
        "id": int(row.get("id") or 0),
        "review_no": str(row.get("topup_no") or f"TOPUP-{row.get('id')}"),
        "type_label": "儲值",
        "reference_label": str(row.get("topup_no") or f"TOPUP-{row.get('id')}"),
        "customer_name": str(row.get("customer_display_name") or row.get("customer_discord_id") or "—"),
        "customer_id": str(row.get("customer_discord_id") or ""),
        "amount": int(row.get("amount") or 0),
        "payment_method": topup_payment_method_label(payment_method),
        "payment_reference_label": topup_payment_reference_label(payment_method),
        "payment_reference_display": payment_reference,
        "ticket_channel_id": "",
        "ticket_url": "",
        "status": status,
        "status_label": topup_status_label(status),
        "status_bucket": _topup_bucket(status),
        "submitted_at": str(row.get("submitted_at") or row.get("created_at") or ""),
        "rejected_reason": str(row.get("rejected_reason") or ""),
        "last_error": "",
        "actionable": status == "pending_review",
    }


@router.get("/admin/payment-reviews", response_class=HTMLResponse)
async def admin_payment_reviews(
    request: Request,
    status: str | None = "pending",
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    selected_status = _normalize_status(status)
    rows = [_decorate_external(row) for row in list_payment_reviews(limit=300)]
    rows.extend(_decorate_topup(row) for row in list_topups_for_admin(limit=300))

    if selected_status != "all":
        rows = [row for row in rows if row["status_bucket"] == selected_status]

    rows.sort(
        key=lambda row: (
            row["status_bucket"] != "pending",
            str(row.get("submitted_at") or ""),
        ),
        reverse=False,
    )

    counts = {
        "pending": sum(1 for row in rows if row["status_bucket"] == "pending")
        if selected_status == "all"
        else None,
    }

    all_external = [_decorate_external(row) for row in list_payment_reviews(limit=300)]
    all_topups = [_decorate_topup(row) for row in list_topups_for_admin(limit=300)]
    all_rows = all_external + all_topups
    counts = {
        bucket: sum(1 for row in all_rows if row["status_bucket"] == bucket)
        for bucket in ("pending", "processing", "completed", "rejected", "failed")
    }

    return templates.TemplateResponse(
        request=request,
        name="admin_payment_reviews.html",
        context={
            "title": "付款審核",
            "user": user,
            "rows": rows,
            "status_filter": selected_status,
            "counts": counts,
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@router.post("/admin/payment-reviews/{review_id}/approve")
async def admin_payment_review_approve(request: Request, review_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    try:
        approve_payment_review(
            review_id,
            operator_discord_id=str(user.get("id") or ""),
            operator_display_name=_display_name(user),
        )
    except ValueError as exc:
        return _redirect_message("error", exc)

    return _redirect_message(
        "ok",
        "已核准，Bot 將自動回原票口完成付款流程。",
    )


@router.post("/admin/payment-reviews/{review_id}/reject")
async def admin_payment_review_reject(
    request: Request,
    review_id: int,
    reason: str = Form(default="客服駁回"),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    try:
        reject_payment_review(
            review_id,
            operator_discord_id=str(user.get("id") or ""),
            operator_display_name=_display_name(user),
            reason=reason,
        )
    except ValueError as exc:
        return _redirect_message("error", exc)

    return _redirect_message(
        "ok",
        "已駁回，Bot 將自動回原票口通知老闆。",
    )


@router.post("/admin/payment-reviews/topup/{topup_id}/approve")
async def admin_payment_review_topup_approve(request: Request, topup_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    try:
        approve_topup_order(
            topup_id,
            operator_discord_id=str(user.get("id") or ""),
            operator_display_name=_display_name(user),
        )
    except ValueError as exc:
        return _redirect_message("error", exc)

    return _redirect_message(
        "ok",
        "儲值已核准，Bot 將自動完成錢包與 VIP 入帳。",
    )


@router.post("/admin/payment-reviews/topup/{topup_id}/reject")
async def admin_payment_review_topup_reject(
    request: Request,
    topup_id: int,
    reason: str = Form(default="客服駁回"),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    try:
        reject_topup_order(
            topup_id,
            operator_discord_id=str(user.get("id") or ""),
            reason=reason,
        )
    except ValueError as exc:
        return _redirect_message("error", exc)

    return _redirect_message("ok", "儲值付款已駁回。")
