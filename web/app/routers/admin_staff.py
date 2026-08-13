from __future__ import annotations

from inspect import signature
from pathlib import Path
from urllib.parse import urlencode
import json

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember
from web.app.services.role_catalog import (
    COMPANION_ROLE_IDS,
    CUSTOMER_SERVICE_LABEL,
    CUSTOMER_SERVICE_ROLE_ID,
    RECEIVER_ROLE_IDS,
    STAFF_ROLE_FILTERS,
    receiver_labels_from_roles,
)
from web.app.services.staff_service import sync_staff_members_from_discord


router = APIRouter(tags=["admin-staff"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

VALID_STAFF_ROLE_FILTERS = {option["value"] for option in STAFF_ROLE_FILTERS}
VALID_STAFF_ROLE_FILTERS |= {"all", "worker", "companion"}


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


def get_member_receiver_labels(member: WebStaffMember) -> list[str]:
    try:
        role_ids = json.loads(member.roles_json or "[]")
    except Exception:
        role_ids = []

    return receiver_labels_from_roles(role_ids)


def prepare_member_labels(members: list[WebStaffMember]) -> list[WebStaffMember]:
    for member in members:
        try:
            member.receiver_role_labels = get_member_receiver_labels(member)
        except Exception:
            pass

    return members


def member_matches_keyword(member: WebStaffMember, keyword: str) -> bool:
    if not keyword:
        return True

    keyword = keyword.lower()

    return (
        keyword in str(member.display_name or "").lower()
        or keyword in str(member.username or "").lower()
        or keyword in str(member.global_name or "").lower()
        or keyword in str(member.discord_id or "").lower()
        or keyword in str(member.roles_json or "").lower()
    )



def reclassify_staff_members(db) -> None:
    all_members = list(db.scalars(select(WebStaffMember)).all())

    customer_service_role_ids = {CUSTOMER_SERVICE_ROLE_ID}

    for member in all_members:
        try:
            role_ids = set(json.loads(member.roles_json or "[]"))
        except Exception:
            role_ids = set()

        member.is_customer_service = bool(role_ids & customer_service_role_ids)
        member.is_worker = bool(role_ids & RECEIVER_ROLE_IDS)
        member.is_companion = bool(role_ids & COMPANION_ROLE_IDS)
        member.is_active = bool(
            member.is_customer_service
            or member.is_worker
            or member.is_companion
        )


def build_sync_message(result) -> str:
    if isinstance(result, dict):
        if result.get("message"):
            return str(result["message"])

        scanned = (
            result.get("scanned")
            or result.get("scanned_count")
            or result.get("total")
            or result.get("total_members")
            or result.get("fetched")
            or "?"
        )
        written = (
            result.get("written")
            or result.get("written_count")
            or result.get("upserted")
            or result.get("synced")
            or result.get("saved")
            or "?"
        )

        return f"成員同步完成：掃描 {scanned} 人，寫入 {written} 人。"

    return "成員同步完成。"


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

    if role not in VALID_STAFF_ROLE_FILTERS:
        role = "all"

    if status not in {"active", "inactive", "all"}:
        status = "active"

    db = SessionLocal()

    try:
        all_members = list(db.scalars(select(WebStaffMember)).all())

        active_members = [member for member in all_members if member.is_active]
        inactive_members = [member for member in all_members if not member.is_active]

        if status == "inactive":
            members = inactive_members
        elif status == "all":
            members = all_members
        else:
            members = active_members

        if role == "customer_service":
            members = [member for member in members if member.is_customer_service]
        elif role in RECEIVER_ROLE_IDS:
            members = [
                member
                for member in members
                if role in str(member.roles_json or "")
            ]
        elif role == "worker":
            members = [member for member in members if member.is_worker]
        elif role == "companion":
            members = [member for member in members if member.is_companion]

        keyword = q.strip()
        if keyword:
            members = [
                member
                for member in members
                if member_matches_keyword(member, keyword)
            ]

        members.sort(
            key=lambda member: str(
                member.display_name
                or member.global_name
                or member.username
                or member.discord_id
            )
        )

        prepare_member_labels(members)

        stats = {
            "total": len(all_members),
            "active": len(active_members),
            "inactive": len(inactive_members),
            "customer_service": len([
                member for member in active_members
                if member.is_customer_service
            ]),
            "worker": len([
                member for member in active_members
                if member.is_worker
            ]),
            "companion": len([
                member for member in active_members
                if member.is_companion
            ]),
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
            "role_filter_options": STAFF_ROLE_FILTERS,
            "staff_role_filters": STAFF_ROLE_FILTERS,
            "customer_service_label": CUSTOMER_SERVICE_LABEL,
        },
    )


async def run_admin_staff_sync(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
        db.commit()
        query = {"message": build_sync_message(result)}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        print("[admin_staff_sync_error]", repr(exc))
        query = {"error": f"成員同步失敗：{exc}"}
    finally:
        db.close()

    return RedirectResponse(
        url=f"/admin/staff?{urlencode(query)}",
        status_code=303,
    )


@router.post("/admin/staff/sync")
async def admin_staff_sync(request: Request):
    return await run_admin_staff_sync(request)


@router.get("/admin/staff/sync")
async def admin_staff_sync_get(request: Request):
    return await run_admin_staff_sync(request)

