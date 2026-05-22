from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import AdminAuditLog

router = APIRouter(tags=["admin-audit"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def parse_json_text(value: str | None) -> str:
    if not value:
        return ""

    try:
        parsed = json.loads(value)
    except Exception:
        return value

    return json.dumps(parsed, ensure_ascii=False, indent=2)


@router.get("/admin/audit")
async def admin_audit_logs(request: Request, action: str | None = None, admin_id: str | None = None):
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
                "message": "你沒有總控後台權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        statement = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())

        if action:
            statement = statement.where(AdminAuditLog.action == action)

        if admin_id:
            statement = statement.where(AdminAuditLog.admin_discord_id == admin_id)

        logs = list(db.scalars(statement.limit(300)).all())

        actions = [
            row[0]
            for row in db.execute(
                select(AdminAuditLog.action).distinct().order_by(AdminAuditLog.action.asc())
            ).all()
        ]
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_audit.html",
        context={
            "title": "操作紀錄",
            "user": user,
            "logs": logs,
            "actions": actions,
            "selected_action": action or "",
            "admin_id": admin_id or "",
            "parse_json_text": parse_json_text,
        },
    )
