from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web.app.routers.admin_staff_profiles import (
    _date_text,
    _discord_link,
    _fetch_profile,
    _fetch_profiles,
    _fetch_recent_profile_stats,
    _is_admin,
    _staff_profile_sync_command,
)


router = APIRouter(prefix="/admin/staff_profiles", tags=["admin-staff-profiles-ui"])

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _profile_view(row, recent_stats: dict[str, dict]) -> dict:
    staff_id = str(row["staff_discord_id"] or "").strip()
    profile_recent_stats = recent_stats.get(staff_id, {})
    thread_id = str(row["forum_thread_id"] or "").strip()
    message_id = str(row["panel_message_id"] or "").strip()

    return {
        "staff_id": staff_id,
        "display_name": str(row["display_name"] or staff_id),
        "profile_type": str(row["profile_type"] or "成員"),
        "role_title": str(row["role_title"] or ""),
        "main_games": str(row["main_games"] or ""),
        "service_tags": str(row["service_tags"] or ""),
        "bio": str(row["bio"] or ""),
        "card_image_url": str(row["card_image_url"] or ""),
        "favorite_count": int(row["favorite_count"] or 0),
        "completed_count": int(row["completed_count"] or 0),
        "review_count": int(row["review_count"] or 0),
        "average_rating": float(row["average_rating"] or 0),
        "recent_completed_count": int(
            profile_recent_stats.get("recent_completed_count") or 0
        ),
        "recent_review_count": int(
            profile_recent_stats.get("recent_review_count") or 0
        ),
        "latest_review_at": _date_text(
            profile_recent_stats.get("latest_review_at")
        ),
        "is_public": int(row["is_public"] or 0) == 1,
        "updated_at": str(row["updated_at"] or ""),
        "discord_link": _discord_link(row),
        "has_panel": bool(thread_id and message_id),
        "thread_id": thread_id,
        "message_id": message_id,
        "sync_command": _staff_profile_sync_command(staff_id),
    }


@router.get("/")
async def staff_profiles_index_ui(request: Request):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    profiles = _fetch_profiles()
    recent_stats = _fetch_recent_profile_stats()
    rows = [_profile_view(row, recent_stats) for row in profiles]

    stats = {
        "total": len(rows),
        "public": sum(1 for row in rows if row["is_public"]),
        "hidden": sum(1 for row in rows if not row["is_public"]),
        "panel_ready": sum(1 for row in rows if row["has_panel"]),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin_staff_profiles_r5.html",
        context={
            "title": "個人牆管理",
            "rows": rows,
            "stats": stats,
        },
    )


@router.get("/edit/{staff_discord_id}")
async def edit_staff_profile_ui(request: Request, staff_discord_id: str):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    row = _fetch_profile(staff_discord_id)
    if row is None:
        return RedirectResponse(url="/admin/staff_profiles/", status_code=303)

    profile = {
        "staff_id": str(row["staff_discord_id"] or ""),
        "display_name": str(row["display_name"] or ""),
        "profile_type": str(row["profile_type"] or ""),
        "role_title": str(row["role_title"] or ""),
        "main_games": str(row["main_games"] or ""),
        "service_tags": str(row["service_tags"] or ""),
        "bio": str(row["bio"] or ""),
        "card_image_url": str(row["card_image_url"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin_staff_profile_edit_r5.html",
        context={
            "title": "編輯個人牆",
            "profile": profile,
        },
    )
