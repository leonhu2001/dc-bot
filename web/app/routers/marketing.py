from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.marketing_funnel import (
    build_marketing_snapshot,
    record_marketing_event,
)


router = APIRouter(tags=["marketing"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


@router.post("/marketing/event")
async def marketing_event(
    request: Request,
):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "invalid payload"},
            status_code=400,
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            {"ok": False, "error": "invalid payload"},
            status_code=400,
        )

    user = _current_user(request)
    customer_id = str(user.get("id") or "") if user else None

    try:
        await run_in_threadpool(
            record_marketing_event,
            session=request.session,
            event_name=str(payload.get("event_name") or ""),
            path=str(payload.get("path") or request.url.path),
            customer_discord_id=customer_id,
            properties=payload.get("properties"),
        )
    except ValueError:
        return JSONResponse(
            {"ok": False, "error": "unsupported event"},
            status_code=422,
        )
    except Exception as exc:
        print(
            f"[marketing-event] {type(exc).__name__}: {exc}",
            flush=True,
        )
        return JSONResponse(
            {"ok": False, "error": "event unavailable"},
            status_code=503,
        )

    return JSONResponse({"ok": True})


@router.get("/admin/marketing")
async def admin_marketing(
    request: Request,
    days: int = 30,
):
    user = _current_user(request)

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/no-access", status_code=303)

    if not user.get("is_manager"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "行銷漏斗僅限總管查看。",
                "user": user,
            },
            status_code=403,
        )

    snapshot = await run_in_threadpool(
        build_marketing_snapshot,
        days=days,
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_marketing.html",
        context={
            "title": "行銷漏斗｜魔丸娛樂",
            "user": user,
            "snapshot": snapshot,
            "days": snapshot["days"],
        },
    )
