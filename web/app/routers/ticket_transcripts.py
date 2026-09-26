from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from shared.db import SessionLocal
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids


router = APIRouter(tags=["ticket-transcripts"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _authorized_user(request: Request) -> dict | None:
    user = dict(request.session.get("user") or {})
    discord_id = str(user.get("id") or "").strip()
    if not discord_id:
        return None

    try:
        role_ids = get_member_role_ids(discord_id)
        access = get_dashboard_access(role_ids)
    except Exception:
        return None

    is_manager = bool(
        access.get("is_manager", False)
        or access.get("is_admin", False)
    )
    is_customer_service = bool(
        access.get("is_customer_service", False)
    )

    if not (is_manager or is_customer_service):
        return None

    user.update(
        {
            "role_ids": list(role_ids),
            "is_manager": is_manager,
            "is_admin": bool(is_manager or is_customer_service),
            "is_customer_service": is_customer_service,
        }
    )
    request.session["user"] = user
    return user


def _format_row(row) -> dict:
    item = dict(row)
    try:
        item["participants"] = json.loads(item.get("participants_json") or "[]")
    except Exception:
        item["participants"] = []
    return item


@router.get("/employee/tickets", response_class=HTMLResponse)
async def employee_ticket_transcripts(
    request: Request,
    q: str = "",
):
    user = _authorized_user(request)
    if not user:
        return RedirectResponse(url="/me?denied=ticket-transcripts", status_code=303)

    key = str(q or "").strip()
    db = SessionLocal()
    try:
        if key:
            rows = db.execute(
                text(
                    """
                    SELECT *
                    FROM ticket_transcripts
                    WHERE channel_name LIKE :key
                       OR customer_display_name LIKE :key
                       OR customer_discord_id LIKE :key
                       OR receipt_id LIKE :key
                       OR ticket_channel_id LIKE :key
                       OR CAST(order_id AS TEXT) LIKE :key
                    ORDER BY closed_at DESC, id DESC
                    LIMIT 200
                    """
                ),
                {"key": f"%{key}%"},
            ).mappings().all()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT *
                    FROM ticket_transcripts
                    ORDER BY closed_at DESC, id DESC
                    LIMIT 200
                    """
                )
            ).mappings().all()

        transcripts = [_format_row(row) for row in rows]
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="employee_ticket_transcripts.html",
        context={
            "title": "票口聊天紀錄｜魔丸娛樂",
            "page_name": "employee",
            "user": user,
            "q": q,
            "transcripts": transcripts,
        },
    )


@router.get("/employee/tickets/{transcript_id}", response_class=HTMLResponse)
async def employee_ticket_transcript_detail(
    transcript_id: int,
    request: Request,
):
    user = _authorized_user(request)
    if not user:
        return RedirectResponse(url="/me?denied=ticket-transcripts", status_code=303)

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT *
                FROM ticket_transcripts
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": int(transcript_id)},
        ).mappings().first()
    finally:
        db.close()

    if row is None:
        return RedirectResponse(
            url="/employee/tickets?error=not_found",
            status_code=303,
        )

    transcript = _format_row(row)

    return templates.TemplateResponse(
        request=request,
        name="employee_ticket_transcript_detail.html",
        context={
            "title": f"{transcript.get('channel_name') or '票口'}｜聊天紀錄",
            "page_name": "employee",
            "user": user,
            "transcript": transcript,
        },
    )


@router.get("/employee/tickets/{transcript_id}/text", response_class=PlainTextResponse)
async def employee_ticket_transcript_text(
    transcript_id: int,
    request: Request,
):
    user = _authorized_user(request)
    if not user:
        return PlainTextResponse("Forbidden", status_code=403)

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT transcript_text, channel_name
                FROM ticket_transcripts
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": int(transcript_id)},
        ).mappings().first()
    finally:
        db.close()

    if row is None:
        return PlainTextResponse("Not Found", status_code=404)

    return PlainTextResponse(
        str(row.get("transcript_text") or ""),
        headers={
            "Content-Disposition": (
                f'inline; filename="ticket-transcript-{int(transcript_id)}.txt"'
            )
        },
    )
