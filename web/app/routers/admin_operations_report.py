from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from web.app.routers.admin_payout_summary import current_user, require_admin
from web.app.services.operations_report import build_operations_report


router = APIRouter(tags=["admin_operations_report"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/admin/payouts/report")
async def admin_operations_report(
    request: Request,
    period: str | None = "quarter",
):
    user = require_admin(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
                "user": current_user(request),
            },
            status_code=403,
        )

    report = build_operations_report(period)
    return templates.TemplateResponse(
        request=request,
        name="admin_operations_report_v2.html",
        context={
            "title": "營運財務報表",
            "user": user,
            "report": report,
        },
    )
