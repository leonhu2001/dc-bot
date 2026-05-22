from pathlib import Path
from urllib.parse import urlencode

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


def redirect_to_staff(**params) -> RedirectResponse:
    query = {key: value for key, value in params.items() if value not in (None, "")}
    url = "/admin/staff"
    if query:
        url = f"{url}?{urlencode(query)}"
    return RedirectResponse(url=url, status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


@router.get("/admin/staff")
async def admin_staff_page(
    request: Request,
    role: str = "all",
    active: str = "active",
    message: str | None = None,
    error: str | None = None,
):
    user = get_current_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={"title": "請先登入", "message": "請先使用 Discord 登入。", "user": None},
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={"title": "沒有權限", "message": "你沒有總控後台權限。", "user": user},
            status_code=403,
        )

    db = SessionLocal()
    try:
        statement = select(WebStaffMember)

        if active == "active":
            statement = statement.where(WebStaffMember.is_active.is_(True))
        elif active == "inactive":
            statement = statement.where(WebStaffMember.is_active.is_(False))

        if role == "customer_service":
            statement = statement.where(WebStaffMember.is_customer_service.is_(True))
        elif role == "worker":
            statement = (
                statement
                .where(WebStaffMember.is_worker.is_(True))
                .where(WebStaffMember.is_companion.is_(False))
            )
        elif role == "companion":
            statement = statement.where(WebStaffMember.is_companion.is_(True))

        members = list(
            db.scalars(
                statement.order_by(
                    WebStaffMember.is_active.desc(),
                    WebStaffMember.display_name.asc(),
                    WebStaffMember.username.asc(),
                )
            ).all()
        )

        all_members = list(db.scalars(select(WebStaffMember)).all())
        active_members = [member for member in all_members if member.is_active]
        stats = {
            "total": len(all_members),
            "active": len(active_members),
            "customer_service": sum(1 for member in active_members if member.is_customer_service),
            "worker": sum(1 for member in active_members if member.is_worker and not member.is_companion),
            "companion": sum(1 for member in active_members if member.is_companion),
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
            "active": active,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/staff/sync-now")
async def admin_staff_sync_now(request: Request):
    user = require_admin_user(request)
    if not user:
        return redirect_to_staff(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()
    try:
        result = sync_staff_members_from_discord(db)
    except Exception as e:
        db.rollback()
        return redirect_to_staff(error=f"同步成員失敗：{e}")
    finally:
        db.close()

    return redirect_to_staff(
        message=f"成員同步完成：掃描 {result['total_seen']} 人，寫入 {result['synced_count']} 人，停用 {result['disabled_count']} 人。"
    )
