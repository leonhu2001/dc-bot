from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.payment_reviews import (
    PAYMENT_REVIEW_APPLIED,
    PAYMENT_REVIEW_APPROVED,
    PAYMENT_REVIEW_PENDING,
    PAYMENT_REVIEW_REJECTED,
    approve_payment_review,
    list_payment_reviews,
    reject_payment_review,
    source_label,
)
from services.topups import (
    approve_topup_order,
    list_topups_for_admin,
    reject_topup_order,
    topup_payment_method_label,
    topup_status_label,
)
from web.app.routers.admin_staff import require_admin

router = APIRouter(tags=["payment_reviews"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _display_name(user: dict) -> str:
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "客服"
    )


def _redirect(key: str, message: object, *, status: str = "") -> RedirectResponse:
    query = f"{key}={quote(str(message), safe='')}"
    if status:
        query += f"&status={quote(status, safe='')}"
    return RedirectResponse(
        f"/admin/payment-reviews?{query}",
        status_code=303,
    )


def _review_status_label(status: str | None) -> str:
    value = str(status or "").strip()
    return {
        PAYMENT_REVIEW_PENDING: "待審核",
        PAYMENT_REVIEW_APPROVED: "已核准，等待 Bot 套用",
        PAYMENT_REVIEW_APPLIED: "已完成",
        PAYMENT_REVIEW_REJECTED: "已駁回",
        "apply_error": "套用失敗",
    }.get(value, value or "未知")


def _review_entry(row: dict) -> dict:
    item = dict(row)
    item["kind"] = str(item.get("source_type") or "")
    item["kind_label"] = source_label(item.get("source_type"))
    item["display_no"] = str(
        item.get("review_no")
        or f"PAY-{item.get('id')}"
    )
    item["source_display"] = (
        f"WEB-{item.get('source_id')}"
        if item.get("source_type") == "order"
        else f"TIP-{item.get('source_id')}"
    )
    item["amount_text"] = f"{int(item.get('amount') or 0):,}T"
    item["payment_method_label"] = str(item.get("payment_method") or "—")
    item["status_label"] = _review_status_label(item.get("status"))
    item["is_pending"] = str(item.get("status") or "") == PAYMENT_REVIEW_PENDING
    item["created_sort"] = str(item.get("created_at") or "")
    item["customer_display"] = (
        str(item.get("customer_display_name") or "").strip()
        or str(item.get("customer_discord_id") or "")
        or "—"
    )
    item["target_display"] = (
        str(item.get("target_display_name") or "").strip()
        or str(item.get("target_discord_id") or "")
        or "—"
    )
    return item


def _topup_entry(row: dict) -> dict:
    item = dict(row)
    status = str(item.get("status") or "")
    item["kind"] = "topup"
    item["kind_label"] = "儲值"
    item["display_no"] = str(item.get("topup_no") or f"TOPUP-{item.get('id')}")
    item["source_display"] = item["display_no"]
    item["amount_text"] = f"{int(item.get('amount') or 0):,}T"
    item["payment_method_label"] = topup_payment_method_label(item.get("payment_method"))
    item["status_label"] = topup_status_label(status)
    item["is_pending"] = status == "pending_review"
    item["created_sort"] = str(item.get("created_at") or "")
    item["customer_display"] = (
        str(item.get("customer_display_name") or "").strip()
        or str(item.get("customer_discord_id") or "")
        or "—"
    )
    item["target_display"] = "錢包"
    item["payment_reference_display"] = (
        str(item.get("payment_reference") or "").strip()
        or str(item.get("bank_last5") or "").strip()
        or "—"
    )
    return item


@router.get("/admin/payment-reviews", response_class=HTMLResponse)
async def admin_payment_reviews(request: Request, status: str | None = ""):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    reviews = [_review_entry(row) for row in list_payment_reviews(limit=500)]
    topups = [_topup_entry(row) for row in list_topups_for_admin(limit=500)]

    entries = [*reviews, *topups]

    status_filter = str(status or "").strip()
    if status_filter == "pending":
        entries = [item for item in entries if item.get("is_pending")]
    elif status_filter == "completed":
        entries = [
            item for item in entries
            if (
                (item.get("kind") == "topup" and str(item.get("status")) == "completed")
                or (item.get("kind") != "topup" and str(item.get("status")) == PAYMENT_REVIEW_APPLIED)
            )
        ]
    elif status_filter == "rejected":
        entries = [
            item for item in entries
            if str(item.get("status")) == "rejected"
        ]

    entries.sort(
        key=lambda item: str(item.get("created_sort") or ""),
        reverse=True,
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_payment_reviews.html",
        context={
            "title": "付款審核",
            "user": user,
            "entries": entries,
            "status_filter": status_filter,
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
        return _redirect("error", exc, status="pending")

    return _redirect(
        "ok",
        "付款已核准，Bot 將自動回原票口完成後續。",
        status="pending",
    )


@router.post("/admin/payment-reviews/{review_id}/reject")
async def admin_payment_review_reject(
    request: Request,
    review_id: int,
    reason: str = Form(default="客服未確認到款項"),
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
        return _redirect("error", exc, status="pending")

    return _redirect(
        "ok",
        "付款已駁回，Bot 將通知原票口。",
        status="pending",
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
        return _redirect("error", exc, status="pending")

    return _redirect(
        "ok",
        "儲值付款已核准，Bot 將自動完成錢包與 VIP 入帳。",
        status="pending",
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
        return _redirect("error", exc, status="pending")

    return _redirect("ok", "儲值付款已駁回。", status="pending")
