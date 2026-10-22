from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.routers.admin_common import require_admin_user
from web.app.services.lottery_admin import (
    build_lottery_admin_snapshot,
    save_lottery_settings,
)


router = APIRouter(tags=["admin-lottery"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect(*, message: str = "", error: str = "") -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    query = "?" + urlencode(params) if params else ""
    return RedirectResponse(url="/admin/lottery" + query, status_code=303)


@router.get("/admin/lottery")
async def admin_lottery(
    request: Request,
    message: str = "",
    error: str = "",
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)

    snapshot = await run_in_threadpool(build_lottery_admin_snapshot)
    return templates.TemplateResponse(
        request=request,
        name="admin_lottery.html",
        context={
            "title": "抽獎管理｜魔丸娛樂",
            "user": user,
            "snapshot": snapshot,
            "message": str(message or ""),
            "error": str(error or ""),
        },
    )


@router.post("/admin/lottery/settings")
async def admin_lottery_settings(
    request: Request,
    period: str = Form(...),
    title: str = Form(...),
    prizes: str = Form(default=""),
    note: str = Form(default=""),
    status: str = Form(default="open"),
    cost_per_chance: int = Form(default=5),
    max_chances_per_user: int = Form(default=20),
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)

    try:
        await run_in_threadpool(
            save_lottery_settings,
            period=period,
            title=title,
            prizes=prizes,
            note=note,
            status=status,
            cost_per_chance=int(cost_per_chance),
            max_chances_per_user=int(max_chances_per_user),
        )
    except (ValueError, TypeError) as exc:
        return _redirect(error=str(exc))
    except Exception as exc:
        return _redirect(error=f"儲存抽獎設定失敗：{type(exc).__name__}")

    return _redirect(message="點數抽獎設定已更新。")


__all__ = ["router"]
