from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)
from web.app.services.accounting_repair import (
    QUEUE_WALLET_ORDER_RECONCILIATION,
    RECALCULATE_UNPAID_PAYOUTS,
    VOID_CANCELLED_PAYOUTS,
    apply_accounting_repair,
)


router = APIRouter(tags=["admin-accounting-reconciliation"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def repair_action_label(action: str | None) -> str:
    mapping = {
        QUEUE_WALLET_ORDER_RECONCILIATION: "排入錢包差額修復",
        RECALCULATE_UNPAID_PAYOUTS: "重算未發放分潤",
        VOID_CANCELLED_PAYOUTS: "取消單分潤標記 void",
    }
    return mapping.get(str(action or ""), "安全修復")


@router.get("/admin/accounting-reconciliation")
async def admin_accounting_reconciliation(
    request: Request,
    repair_status: str | None = Query(default=None),
    repair_message: str | None = Query(default=None),
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

    if not user.get("is_manager"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "帳務對帳中心僅限總管使用。",
                "user": user,
            },
            status_code=403,
        )

    reconciliation = await run_in_threadpool(
        build_accounting_reconciliation_snapshot,
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_accounting_reconciliation.html",
        context={
            "title": "帳務對帳中心",
            "user": user,
            "reconciliation": reconciliation,
            "repair_status": str(repair_status or "").strip(),
            "repair_message": str(repair_message or "").strip(),
            "repair_action_label": repair_action_label,
        },
    )


@router.post("/admin/accounting-reconciliation/repair")
async def admin_accounting_reconciliation_repair(
    request: Request,
    order_id: int = Form(...),
    action: str = Form(...),
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

    if not user.get("is_manager"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "帳務修復僅限總管使用。",
                "user": user,
            },
            status_code=403,
        )

    try:
        result = await run_in_threadpool(
            lambda: apply_accounting_repair(
                order_id=int(order_id),
                action=str(action),
                actor=user,
            )
        )
        status = "success"
        message = (
            f"WEB-{int(order_id)}："
            f"{result.get('message') or '安全修復完成。'}"
        )
    except ValueError as exc:
        status = "error"
        message = f"WEB-{int(order_id)}：{exc}"
    except Exception as exc:
        status = "error"
        message = (
            f"WEB-{int(order_id)} 修復失敗："
            f"{type(exc).__name__}。資料已回滾，請查看服務日誌。"
        )

    return RedirectResponse(
        url=(
            "/admin/accounting-reconciliation"
            f"?repair_status={quote_plus(status)}"
            f"&repair_message={quote_plus(message)}"
        ),
        status_code=303,
    )
