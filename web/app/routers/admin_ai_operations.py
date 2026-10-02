from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.ai_operations import (
    build_safe_operations_snapshot,
    generate_operations_analysis,
)
from web.app.services.audit_trail import write_sqlite_audit_log


router = APIRouter(tags=["admin-ai-operations"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_ALLOWED_PERIODS = {"month", "quarter", "year", "all"}


def _manager(request: Request) -> dict | None:
    user = request.session.get("user")
    if not isinstance(user, dict):
        return None
    if not user.get("is_manager"):
        return None
    return user


def _period(value: str | None) -> str:
    clean = str(value or "quarter").strip().lower()
    return clean if clean in _ALLOWED_PERIODS else "quarter"


def _no_access(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="no_access.html",
        context={
            "title": "沒有權限",
            "message": "AI 營運分析僅限總管使用。",
            "user": request.session.get("user"),
        },
        status_code=403,
    )


@router.get("/admin/ai-operations")
async def admin_ai_operations(
    request: Request,
    period: str | None = "quarter",
):
    user = _manager(request)
    if user is None:
        return _no_access(request)

    clean_period = _period(period)
    snapshot = await run_in_threadpool(
        build_safe_operations_snapshot,
        clean_period,
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_ai_operations.html",
        context={
            "title": "AI 營運分析｜魔丸娛樂",
            "user": user,
            "period": clean_period,
            "snapshot": snapshot,
            "analysis": None,
            "question": "",
            "used_external_ai": None,
        },
    )


@router.post("/admin/ai-operations/analyze")
async def admin_ai_operations_analyze(
    request: Request,
    period: str = Form("quarter"),
    question: str = Form(""),
):
    user = _manager(request)
    if user is None:
        return _no_access(request)

    clean_period = _period(period)
    clean_question = str(question or "").strip()[:1200]

    snapshot = await run_in_threadpool(
        build_safe_operations_snapshot,
        clean_period,
    )
    analysis, used_external_ai = await generate_operations_analysis(
        question=clean_question,
        snapshot=snapshot,
    )

    await run_in_threadpool(
        write_sqlite_audit_log,
        admin_discord_id=str(user.get("id") or ""),
        action="ai_operations_analyze",
        target_type="operations_snapshot",
        target_id=clean_period,
        before=None,
        after={
            "period": clean_period,
            "question_length": len(clean_question),
            "external_ai_used": bool(used_external_ai),
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_ai_operations.html",
        context={
            "title": "AI 營運分析｜魔丸娛樂",
            "user": user,
            "period": clean_period,
            "snapshot": snapshot,
            "analysis": analysis,
            "question": clean_question,
            "used_external_ai": used_external_ai,
        },
    )
