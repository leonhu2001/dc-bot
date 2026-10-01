from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.anomaly_detection import build_anomaly_snapshot


router = APIRouter(tags=["admin-anomalies"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/admin/anomalies")
async def admin_anomalies(
    request: Request,
    severity: str = "",
    category: str = "",
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
                "message": "異常偵測中心僅限總管使用。",
                "user": user,
            },
            status_code=403,
        )

    snapshot = await run_in_threadpool(build_anomaly_snapshot)

    severity_filter = str(severity or "").strip().lower()
    category_filter = str(category or "").strip().lower()

    allowed_severities = {"critical", "warning"}
    allowed_categories = set(snapshot.get("category_labels") or {})

    if severity_filter not in allowed_severities:
        severity_filter = ""
    if category_filter not in allowed_categories:
        category_filter = ""

    issues = list(snapshot.get("issues") or [])
    if severity_filter:
        issues = [
            item
            for item in issues
            if str(item.get("severity") or "") == severity_filter
        ]
    if category_filter:
        issues = [
            item
            for item in issues
            if str(item.get("category") or "") == category_filter
        ]

    return templates.TemplateResponse(
        request=request,
        name="admin_anomalies.html",
        context={
            "title": "異常偵測中心",
            "user": user,
            "snapshot": snapshot,
            "issues": issues,
            "severity_filter": severity_filter,
            "category_filter": category_filter,
        },
    )
