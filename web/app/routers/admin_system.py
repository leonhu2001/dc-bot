from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse


router = APIRouter(tags=["admin-system"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/admin/system")
async def admin_system_health(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    user = get_current_user(request)
    if not isinstance(user, dict) or not user.get("is_manager"):
        return RedirectResponse(url="/no-access", status_code=303)

    # Legacy URL retained for bookmarks. System health + operations monitoring
    # now live in the single System Maintenance workspace.
    return RedirectResponse(
        url=f"/admin/anomalies?days={int(days)}",
        status_code=303,
    )
