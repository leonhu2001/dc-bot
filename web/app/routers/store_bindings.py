from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember
from web.app.services.admin_service import write_admin_audit_log
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids
from web.app.services.store_binding_service import (
    ACTIVE,
    ENDED,
    PENDING,
    REJECTED,
    WITHDRAWN,
    apply_for_store_binding,
    binding_payload,
    end_store_binding,
    get_active_binding,
    get_latest_binding,
    get_pending_binding,
    get_staff_binding_payload,
    grant_store_binding,
    list_binding_candidates,
    list_binding_rows,
    member_display_name,
    reject_store_binding,
    sync_store_binding_role,
    withdraw_store_binding_application,
)


router = APIRouter(tags=["store-bindings"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_user(request: Request) -> dict | None:
    return request.session.get("user")


def _discord_id(user: dict | None) -> str:
    user = user or {}
    return str(user.get("discord_id") or user.get("id") or "").strip()


def _can_manage_session(user: dict | None) -> bool:
    """Fast read-only access check for rendering the management page.

    The session roles were already verified during login / privileged actions. Page
    rendering must not wait on Discord REST on every navigation. Mutating routes
    still call _can_manage() below and therefore revalidate against Discord live.
    """
    if not user:
        return False
    if bool(user.get("is_manager") or user.get("is_customer_service")):
        return True
    role_ids = list(user.get("role_ids") or [])
    if not role_ids:
        return False
    try:
        access = get_dashboard_access(role_ids)
    except Exception:
        return False
    return bool(access.get("is_manager") or access.get("is_customer_service"))


def _can_manage(user: dict | None) -> bool:
    staff_id = _discord_id(user)
    if not staff_id:
        return False
    try:
        access = get_dashboard_access(get_member_role_ids(staff_id))
    except Exception:
        return False
    return bool(access.get("is_manager") or access.get("is_customer_service"))


def _redirect(path: str, *, message: str | None = None, error: str | None = None):
    query = {}
    if message:
        query["message"] = message
    if error:
        query["error"] = error
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(url=f"{path}{suffix}", status_code=303)


def _snapshot(row) -> dict | None:
    return binding_payload(row) if row is not None else None


@router.get("/employee/store-binding/status")
async def employee_store_binding_status(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "請先登入 Discord。"}, status_code=401)

    staff_id = _discord_id(user)
    if not staff_id:
        return JSONResponse({"ok": False, "error": "找不到目前登入帳號。"}, status_code=400)

    with SessionLocal() as db:
        member = db.get(WebStaffMember, staff_id)
        eligible = bool(member and member.is_active and member.is_worker)
        data = get_staff_binding_payload(db, staff_id)
        data["eligible"] = eligible
        return {"ok": True, "data": data}


@router.post("/employee/store-binding/apply")
async def employee_store_binding_apply(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/auth/discord/login?next=/employee", status_code=303)

    staff_id = _discord_id(user)
    db = SessionLocal()
    try:
        apply_for_store_binding(db, staff_discord_id=staff_id)
        db.commit()
        return _redirect("/employee", message="綁店申請已送出，等待客服確認。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee", error=str(exc))
    finally:
        db.close()


@router.post("/employee/store-binding/withdraw")
async def employee_store_binding_withdraw(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/auth/discord/login?next=/employee", status_code=303)

    staff_id = _discord_id(user)
    db = SessionLocal()
    try:
        withdraw_store_binding_application(db, staff_discord_id=staff_id)
        db.commit()
        return _redirect("/employee", message="已撤回綁店申請。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee", error=str(exc))
    finally:
        db.close()


@router.get("/employee/store-bindings")
async def store_binding_management(
    request: Request,
    q: str = "",
    message: str | None = None,
    error: str | None = None,
):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/auth/discord/login?next=/employee/store-bindings", status_code=303)
    if not _can_manage_session(user):
        return RedirectResponse("/no-access", status_code=303)

    q = str(q or "").strip().lower()
    with SessionLocal() as db:
        pending_rows = list_binding_rows(db, status=PENDING)
        active_rows = list_binding_rows(db, status=ACTIVE)
        ended_rows = [
            row
            for row in list_binding_rows(db)
            if row.status in {ENDED, REJECTED, WITHDRAWN}
        ]
        all_ids = {
            str(row.staff_discord_id)
            for row in [*pending_rows, *active_rows, *ended_rows]
        }
        members = {
            str(member.discord_id): member
            for member in db.scalars(
                select(WebStaffMember).where(WebStaffMember.discord_id.in_(all_ids))
            ).all()
        } if all_ids else {}

        def present(row):
            member = members.get(str(row.staff_discord_id))
            data = binding_payload(row)
            data["display_name"] = member_display_name(member, row.staff_discord_id)
            return data

        pending = [present(row) for row in pending_rows]
        active = [present(row) for row in active_rows]
        history = [present(row) for row in ended_rows[:50]]

        if q:
            def matches(item):
                return (
                    q in str(item.get("display_name") or "").lower()
                    or q in str(item.get("staff_discord_id") or "").lower()
                )
            pending = [item for item in pending if matches(item)]
            active = [item for item in active if matches(item)]
            history = [item for item in history if matches(item)]

        candidates = list_binding_candidates(db)
        if q:
            candidates = [
                member for member in candidates
                if q in member_display_name(member).lower()
                or q in str(member.discord_id).lower()
            ]

        now = datetime.utcnow()
        month_key = (now.year, now.month)
        added_this_month = sum(
            1
            for row in active_rows
            if row.started_at is not None
            and (row.started_at.year, row.started_at.month) == month_key
        )
        sync_issues = sum(
            1
            for row in active_rows
            if str(row.discord_sync_status or "") == "error"
        )

        return templates.TemplateResponse(
            request=request,
            name="store_bindings.html",
            context={
                "title": "綁店管理｜魔丸娛樂",
                "user": user,
                "pending": pending,
                "active": active,
                "history": history,
                "candidates": candidates,
                "q": q,
                "message": message,
                "error": error,
                "stats": {
                    "pending": len(pending_rows),
                    "active": len(active_rows),
                    "added_this_month": added_this_month,
                    "sync_issues": sync_issues,
                },
            },
        )


@router.post("/employee/store-bindings/grant")
async def store_binding_grant(request: Request):
    user = _current_user(request)
    if not user or not _can_manage(user):
        return RedirectResponse("/no-access", status_code=303)
    form = await request.form()
    staff_id = str(form.get("staff_discord_id") or "").strip()
    note = str(form.get("note") or "").strip()

    db = SessionLocal()
    try:
        before = _snapshot(get_latest_binding(db, staff_id))
        row = grant_store_binding(
            db,
            staff_discord_id=staff_id,
            actor=user,
            source="staff_granted",
            note=note,
        )
        write_admin_audit_log(
            db,
            admin_user=user,
            action="grant_store_binding",
            target_type="staff_store_binding",
            target_id=staff_id,
            before=before,
            after=_snapshot(row),
        )
        db.commit()
        return _redirect("/employee/store-bindings", message="已直接啟用綁店資格。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee/store-bindings", error=str(exc))
    finally:
        db.close()


@router.post("/employee/store-bindings/{staff_id}/approve")
async def store_binding_approve(request: Request, staff_id: str):
    user = _current_user(request)
    if not user or not _can_manage(user):
        return RedirectResponse("/no-access", status_code=303)
    form = await request.form()
    note = str(form.get("note") or "").strip()

    db = SessionLocal()
    try:
        pending = get_pending_binding(db, staff_id)
        if pending is None:
            raise ValueError("找不到待審核的綁店申請。")
        before = _snapshot(pending)
        row = grant_store_binding(
            db,
            staff_discord_id=staff_id,
            actor=user,
            source="self_application",
            note=note,
        )
        write_admin_audit_log(
            db,
            admin_user=user,
            action="approve_store_binding",
            target_type="staff_store_binding",
            target_id=staff_id,
            before=before,
            after=_snapshot(row),
        )
        db.commit()
        return _redirect("/employee/store-bindings", message="綁店申請已核准。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee/store-bindings", error=str(exc))
    finally:
        db.close()


@router.post("/employee/store-bindings/{staff_id}/reject")
async def store_binding_reject(request: Request, staff_id: str):
    user = _current_user(request)
    if not user or not _can_manage(user):
        return RedirectResponse("/no-access", status_code=303)
    form = await request.form()
    note = str(form.get("note") or "").strip()

    db = SessionLocal()
    try:
        before = _snapshot(get_pending_binding(db, staff_id))
        row = reject_store_binding(db, staff_discord_id=staff_id, actor=user, note=note)
        write_admin_audit_log(
            db,
            admin_user=user,
            action="reject_store_binding",
            target_type="staff_store_binding",
            target_id=staff_id,
            before=before,
            after=_snapshot(row),
        )
        db.commit()
        return _redirect("/employee/store-bindings", message="已拒絕綁店申請。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee/store-bindings", error=str(exc))
    finally:
        db.close()


@router.post("/employee/store-bindings/{staff_id}/end")
async def store_binding_end(request: Request, staff_id: str):
    user = _current_user(request)
    if not user or not _can_manage(user):
        return RedirectResponse("/no-access", status_code=303)
    form = await request.form()
    note = str(form.get("note") or "").strip()

    db = SessionLocal()
    try:
        before = _snapshot(get_active_binding(db, staff_id))
        row = end_store_binding(db, staff_discord_id=staff_id, actor=user, note=note)
        write_admin_audit_log(
            db,
            admin_user=user,
            action="end_store_binding",
            target_type="staff_store_binding",
            target_id=staff_id,
            before=before,
            after=_snapshot(row),
        )
        db.commit()
        return _redirect("/employee/store-bindings", message="已解除綁店資格。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee/store-bindings", error=str(exc))
    finally:
        db.close()


@router.post("/employee/store-bindings/{staff_id}/resync")
async def store_binding_resync(request: Request, staff_id: str):
    user = _current_user(request)
    if not user or not _can_manage(user):
        return RedirectResponse("/no-access", status_code=303)

    db = SessionLocal()
    try:
        row = get_active_binding(db, staff_id)
        if row is None:
            raise ValueError("只有綁店中的人員可以重新同步身分組。")
        sync_store_binding_role(db, binding=row, enabled=True)
        db.commit()
        if row.discord_sync_status == "synced":
            return _redirect("/employee/store-bindings", message="Discord 綁店身分組已重新同步。")
        return _redirect("/employee/store-bindings", error=row.discord_sync_error or "Discord 同步失敗。")
    except ValueError as exc:
        db.rollback()
        return _redirect("/employee/store-bindings", error=str(exc))
    finally:
        db.close()
