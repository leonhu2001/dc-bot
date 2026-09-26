from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from services.ticket_archives import get_ticket_archive, list_ticket_archives
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids


router = APIRouter(tags=["ticket-archives"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def _require_customer_service(request: Request) -> dict | RedirectResponse:
    user = dict(request.session.get("user") or {})
    discord_id = str(user.get("id") or "").strip()

    if not discord_id:
        return RedirectResponse(url="/auth/discord/login", status_code=303)

    try:
        role_ids = await run_in_threadpool(get_member_role_ids, discord_id)
        access = get_dashboard_access(role_ids)
    except Exception:
        access = {"is_customer_service": False, "is_manager": False}

    if not (access.get("is_customer_service") or access.get("is_manager")):
        raise HTTPException(status_code=403, detail="此頁僅限客服／總管查閱。")

    user.update(
        {
            "role_ids": role_ids if "role_ids" in locals() else [],
            "is_customer_service": bool(access.get("is_customer_service")),
            "is_manager": bool(access.get("is_manager")),
            "is_admin": bool(
                access.get("is_customer_service")
                or access.get("is_manager")
            ),
            "is_employee": True,
        }
    )
    request.session["user"] = user
    return user


@router.get("/employee/tickets")
async def ticket_archive_list(
    request: Request,
    q: str = "",
):
    user = await _require_customer_service(request)
    if isinstance(user, RedirectResponse):
        return user

    archives = list_ticket_archives(
        search=q,
        limit=200,
    )

    return templates.TemplateResponse(
        request=request,
        name="employee_ticket_archives.html",
        context={
            "title": "票口紀錄｜魔丸娛樂",
            "page_name": "employee_ticket_archives",
            "user": user,
            "archives": archives,
            "query": str(q or "").strip(),
        },
    )


@router.get("/employee/tickets/{archive_id}")
async def ticket_archive_detail(
    request: Request,
    archive_id: int,
):
    user = await _require_customer_service(request)
    if isinstance(user, RedirectResponse):
        return user

    bundle = get_ticket_archive(int(archive_id))
    if bundle is None:
        raise HTTPException(status_code=404, detail="找不到這份票口紀錄。")

    return templates.TemplateResponse(
        request=request,
        name="employee_ticket_archive_detail.html",
        context={
            "title": "票口聊天紀錄｜魔丸娛樂",
            "page_name": "employee_ticket_archive_detail",
            "user": user,
            **bundle,
        },
    )
