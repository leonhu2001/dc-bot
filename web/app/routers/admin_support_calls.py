from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from services.support_calls import build_support_call_snapshot


router = APIRouter(tags=["admin-support-calls"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/admin/support-calls")
async def admin_support_calls(request: Request, days: int = 30):
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

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "客服鈴紀錄僅限客服與總管使用。",
                "user": user,
            },
            status_code=403,
        )

    snapshot = await run_in_threadpool(
        build_support_call_snapshot,
        days=max(1, min(int(days or 30), 365)),
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_support_calls.html",
        context={
            "title": "客服鈴 / SLA",
            "user": user,
            "snapshot": snapshot,
        },
    )
