from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember
from web.app.services.staff_service import sync_staff_members_from_discord

router = APIRouter(tags=["admin-staff"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


@router.get("/admin/staff")
async def admin_staff_page(
    request: Request,
    role: str = "all",
    status: str = "active",
    q: str = "",
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": get_current_user(request),
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        all_members = list(db.scalars(select(WebStaffMember)).all())

        active_members = [member for member in all_members if member.is_active]
        customer_service_members = [
            member for member in active_members if member.is_customer_service
        ]
        worker_members = [
            member for member in active_members if member.is_worker
        ]
        companion_members = [
            member for member in active_members if member.is_companion
        ]

        members = all_members

        if status == "active":
            members = [member for member in members if member.is_active]
        elif status == "inactive":
            members = [member for member in members if not member.is_active]

        if role == "customer_service":
            members = [member for member in members if member.is_customer_service]
        elif role == "worker":
            members = [member for member in members if member.is_worker]
        elif role == "companion":
            members = [member for member in members if member.is_companion]

        keyword = q.strip().lower()
        if keyword:
            members = [
                member for member in members
                if keyword in str(member.display_name or "").lower()
                or keyword in str(member.username or "").lower()
                or keyword in str(member.discord_id or "").lower()
            ]

        members.sort(
            key=lambda member: (
                not bool(member.is_active),
                str(member.display_name or member.username or member.discord_id),
            )
        )

        stats = {
            "total": len(all_members),
            "active": len(active_members),
            "customer_service": len(customer_service_members),
            "worker": len(worker_members),
            "companion": len(companion_members),
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_staff.html",
        context={
            "title": "人員名單",
            "user": user,
            "members": members,
            "stats": stats,
            "role": role,
            "status": status,
            "q": q,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/staff/sync")
async def admin_staff_sync(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/staff?error=同步失敗：{exc}",
            status_code=303,
        )
    finally:
        db.close()

    return RedirectResponse(
        url=(
            "/admin/staff?message="
            f"同步完成：掃描 {result['total_seen']} 人，寫入 {result['synced_count']} 人。"
        ),
        status_code=303,
    )
