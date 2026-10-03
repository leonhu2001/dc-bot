from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from shared.db import SessionLocal
from shared.models import AdminAuditLog
from web.app.services.anomaly_detection import build_anomaly_snapshot
from web.app.services.anomaly_repair import apply_anomaly_repair
from web.app.services.system_health import build_system_health_snapshot
from web.app.services.operations_monitoring import (
    build_operations_monitoring_snapshot,
)


router = APIRouter(tags=["admin-anomalies"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def _recent_audit_logs(limit: int = 25) -> list[dict]:
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(AdminAuditLog)
                .order_by(AdminAuditLog.id.desc())
                .limit(max(1, min(int(limit or 25), 100)))
            ).all()
        )

    return [
        {
            "id": int(row.id),
            "admin_discord_id": str(row.admin_discord_id or ""),
            "action": str(row.action or ""),
            "target_type": str(row.target_type or ""),
            "target_id": str(row.target_id or ""),
            "created_at": (
                row.created_at.strftime("%Y/%m/%d %H:%M:%S")
                if row.created_at is not None
                else "-"
            ),
        }
        for row in rows
    ]


@router.get("/admin/anomalies")
async def admin_anomalies(
    request: Request,
    severity: str = "",
    category: str = "",
    days: int = 30,
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
                "message": "系統維運中心僅限總管使用。",
                "user": user,
            },
            status_code=403,
        )

    snapshot = await run_in_threadpool(build_anomaly_snapshot)
    health = await run_in_threadpool(build_system_health_snapshot)
    operations = await run_in_threadpool(
        build_operations_monitoring_snapshot,
        days=max(1, min(int(days or 30), 365)),
    )
    audit_logs = await run_in_threadpool(_recent_audit_logs)

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
            "title": "系統維運",
            "user": user,
            "snapshot": snapshot,
            "health": health,
            "operations": operations,
            "audit_logs": audit_logs,
            "issues": issues,
            "severity_filter": severity_filter,
            "category_filter": category_filter,
            "repair_status": str(
                request.query_params.get("repair_status") or ""
            ).strip(),
            "repair_message": str(
                request.query_params.get("repair_message") or ""
            ).strip(),
        },
    )


@router.post("/admin/anomalies/repair")
async def admin_anomaly_repair(
    request: Request,
    action: str = Form(...),
    target_id: int | None = Form(default=None),
    order_id: int | None = Form(default=None),
):
    user = get_current_user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    try:
        result = await run_in_threadpool(
            lambda: apply_anomaly_repair(
                action=str(action),
                target_id=target_id,
                order_id=order_id,
                actor=user,
            )
        )
        status = "success"
        message = str(result.get("message") or "安全修復已完成。")
    except ValueError as exc:
        status = "error"
        message = str(exc)
    except Exception as exc:
        status = "error"
        message = (
            f"修復失敗：{type(exc).__name__}。"
            "資料未完成修改，請查看操作紀錄或服務日誌。"
        )

    return RedirectResponse(
        url=(
            "/admin/anomalies"
            f"?repair_status={quote_plus(status)}"
            f"&repair_message={quote_plus(message)}"
        ),
        status_code=303,
    )
