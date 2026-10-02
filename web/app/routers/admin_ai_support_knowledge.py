from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from services.ai_support_knowledge import (
    approve_candidate,
    archive_knowledge,
    build_knowledge_snapshot,
    create_manual_knowledge,
    get_learning_candidate,
    reject_candidate,
)
from web.app.services.audit_trail import write_sqlite_audit_log


router = APIRouter(tags=["admin-ai-support-knowledge"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_manager(request: Request) -> dict | None:
    user = request.session.get("user")
    if not isinstance(user, dict):
        return None
    if not user.get("is_manager"):
        return None
    return user


def _actor_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("name")
        or user.get("id")
        or "總管"
    )[:200]


def _redirect(notice: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/ai-support-knowledge?notice={notice}",
        status_code=303,
    )


@router.get("/admin/ai-support-knowledge")
async def admin_ai_support_knowledge(request: Request):
    user = _current_manager(request)
    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "AI 客服知識庫僅限總管使用。",
                "user": request.session.get("user"),
            },
            status_code=403,
        )

    snapshot = await run_in_threadpool(build_knowledge_snapshot)

    return templates.TemplateResponse(
        request=request,
        name="admin_ai_support_knowledge.html",
        context={
            "title": "AI 客服知識庫｜魔丸娛樂",
            "user": user,
            "snapshot": snapshot,
            "notice": str(request.query_params.get("notice") or ""),
        },
    )


@router.post("/admin/ai-support-knowledge/candidates/{candidate_id}/approve")
async def approve_learning_candidate(
    request: Request,
    candidate_id: int,
):
    user = _current_manager(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    form = await request.form()
    question = str(form.get("question") or "").strip()
    answer = str(form.get("answer") or "").strip()

    if not question or not answer:
        return _redirect("missing")

    before = await run_in_threadpool(
        get_learning_candidate,
        int(candidate_id),
    )

    try:
        knowledge = await run_in_threadpool(
            approve_candidate,
            int(candidate_id),
            question=question,
            answer=answer,
            reviewed_by_discord_id=str(user.get("id") or ""),
            reviewed_by_display_name=_actor_name(user),
        )
    except ValueError:
        return _redirect("missing")

    if knowledge is None:
        return _redirect("already-reviewed")

    await run_in_threadpool(
        write_sqlite_audit_log,
        admin_discord_id=str(user.get("id") or ""),
        action="ai_support_knowledge_approve",
        target_type="ai_support_learning_candidate",
        target_id=int(candidate_id),
        before={
            "status": str((before or {}).get("status") or ""),
        },
        after={
            "status": "approved",
            "knowledge_id": int(knowledge.get("id") or 0),
        },
    )

    return _redirect("approved")


@router.post("/admin/ai-support-knowledge/candidates/{candidate_id}/reject")
async def reject_learning_candidate(
    request: Request,
    candidate_id: int,
):
    user = _current_manager(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    before = await run_in_threadpool(
        get_learning_candidate,
        int(candidate_id),
    )

    changed = await run_in_threadpool(
        reject_candidate,
        int(candidate_id),
        reviewed_by_discord_id=str(user.get("id") or ""),
        reviewed_by_display_name=_actor_name(user),
    )

    if not changed:
        return _redirect("already-reviewed")

    await run_in_threadpool(
        write_sqlite_audit_log,
        admin_discord_id=str(user.get("id") or ""),
        action="ai_support_knowledge_reject",
        target_type="ai_support_learning_candidate",
        target_id=int(candidate_id),
        before={
            "status": str((before or {}).get("status") or ""),
        },
        after={"status": "rejected"},
    )

    return _redirect("rejected")


@router.post("/admin/ai-support-knowledge/manual")
async def add_manual_knowledge(request: Request):
    user = _current_manager(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    form = await request.form()
    question = str(form.get("question") or "").strip()
    answer = str(form.get("answer") or "").strip()

    if not question or not answer:
        return _redirect("missing")

    try:
        knowledge = await run_in_threadpool(
            create_manual_knowledge,
            question=question,
            answer=answer,
            created_by_discord_id=str(user.get("id") or ""),
            created_by_display_name=_actor_name(user),
        )
    except ValueError:
        return _redirect("missing")

    await run_in_threadpool(
        write_sqlite_audit_log,
        admin_discord_id=str(user.get("id") or ""),
        action="ai_support_knowledge_manual_add",
        target_type="ai_support_knowledge",
        target_id=int(knowledge.get("id") or 0),
        before=None,
        after={
            "status": "active",
            "source_type": "manual",
        },
    )

    return _redirect("added")


@router.post("/admin/ai-support-knowledge/{knowledge_id}/archive")
async def archive_ai_knowledge(
    request: Request,
    knowledge_id: int,
):
    user = _current_manager(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    changed = await run_in_threadpool(
        archive_knowledge,
        int(knowledge_id),
    )

    if not changed:
        return _redirect("already-archived")

    await run_in_threadpool(
        write_sqlite_audit_log,
        admin_discord_id=str(user.get("id") or ""),
        action="ai_support_knowledge_archive",
        target_type="ai_support_knowledge",
        target_id=int(knowledge_id),
        before={"status": "active"},
        after={"status": "archived"},
    )

    return _redirect("archived")
