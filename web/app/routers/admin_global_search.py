from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.admin_global_search import (
    build_customer_360,
    search_admin_customers,
)


router = APIRouter(tags=["admin-global-search"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _require_admin(request: Request) -> dict | None:
    user = request.session.get("user")
    if not user or not user.get("is_admin"):
        return None
    return user


@router.get("/admin/search")
async def admin_global_search(
    request: Request,
    q: str = "",
):
    user = _require_admin(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    query = str(q or "").strip()
    result = await run_in_threadpool(
        search_admin_customers,
        query,
    )

    response = templates.TemplateResponse(
        request=request,
        name="admin_global_search.html",
        context={
            "title": "全域搜尋｜魔丸娛樂",
            "user": user,
            "query": query,
            "search": result,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/admin/search/customer/{customer_discord_id}")
async def admin_customer_360(
    request: Request,
    customer_discord_id: str,
):
    user = _require_admin(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    customer_id = str(customer_discord_id or "").strip()
    bundle = await run_in_threadpool(
        build_customer_360,
        customer_id,
    )

    response = templates.TemplateResponse(
        request=request,
        name="admin_customer_360.html",
        context={
            "title": f"{bundle['identity']['display_name']}｜客戶 360°",
            "user": user,
            "customer": bundle,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
