from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


router = APIRouter(tags=["admin-accounting-reconciliation"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/admin/accounting-reconciliation")
async def admin_accounting_reconciliation(request: Request):
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
        },
    )
