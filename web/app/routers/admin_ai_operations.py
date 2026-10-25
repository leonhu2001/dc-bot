from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.services.accounting_reconciliation_policy import (
    build_accounting_policy_view,
    normalize_anomaly_snapshot,
)
from web.app.services.ai_operations import (
    build_safe_operations_snapshot,
    generate_operations_analysis,
)
from web.app.services.anomaly_detection import build_anomaly_snapshot
from web.app.services.audit_trail import write_sqlite_audit_log


router = APIRouter(tags=["admin-ai-operations"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_ALLOWED_PERIODS = {"month", "quarter", "year", "all"}


def _admin(request: Request) -> dict | None:
    user = request.session.get("user")
    if not isinstance(user, dict):
        return None
    if not user.get("is_admin"):
        return None
    return user


def _period(value: str | None) -> str:
    clean = str(value or "quarter").strip().lower()
    return clean if clean in _ALLOWED_PERIODS else "quarter"


def _compact_anomaly_snapshot(anomaly: dict) -> dict:
    safe_issues = []
    for item in (anomaly.get("issues") or [])[:25]:
        if not isinstance(item, dict):
            continue
        safe_issues.append(
            {
                "category": str(item.get("category") or "")[:80],
                "category_label": str(
                    item.get("category_label") or ""
                )[:80],
                "severity": str(item.get("severity") or "")[:40],
                "title": str(item.get("title") or "")[:200],
                "age_minutes": item.get("age_minutes"),
            }
        )

    return {
        "status": str(anomaly.get("status") or ""),
        "issue_count": int(anomaly.get("issue_count") or 0),
        "critical_count": int(anomaly.get("critical_count") or 0),
        "warning_count": int(anomaly.get("warning_count") or 0),
        "category_counts": dict(anomaly.get("category_counts") or {}),
        "issues": safe_issues,
    }


def _clarify_anomaly_semantics(snapshot: dict) -> dict:
    """Expose accounting as a named subset before rendering or calling AI."""
    anomalies = snapshot.get("anomalies")
    if not isinstance(anomalies, dict):
        anomalies = {}
        snapshot["anomalies"] = anomalies

    category_counts = anomalies.get("category_counts")
    if not isinstance(category_counts, dict):
        category_counts = {}

    anomalies["accounting_issue_count"] = int(
        category_counts.get("accounting") or 0
    )
    snapshot["metric_definitions"] = {
        "anomalies.issue_count": (
            "異常中心全部類別的合計；包含訂單、付款、同步、儲值、客服與帳務，"
            "不可稱為帳務異常數。"
        ),
        "anomalies.accounting_issue_count": (
            "只計帳務對帳異常；與系統維運的帳務對帳指標同源。"
        ),
    }
    return snapshot


def _build_policy_aware_operations_snapshot(period: str) -> dict:
    snapshot = build_safe_operations_snapshot(period)
    anomaly = build_anomaly_snapshot(limit=80)
    _, suppressed_accounting = build_accounting_policy_view(detail_limit=10000)
    anomaly = normalize_anomaly_snapshot(anomaly, suppressed_accounting)
    snapshot["anomalies"] = _compact_anomaly_snapshot(anomaly)
    return _clarify_anomaly_semantics(snapshot)


def _no_access(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="no_access.html",
        context={
            "title": "沒有權限",
            "message": "AI 營運分析僅限客服與管理人員使用。",
            "user": request.session.get("user"),
        },
        status_code=403,
    )


@router.get("/admin/ai-operations")
async def admin_ai_operations(
    request: Request,
    period: str | None = "quarter",
):
    user = _admin(request)
    if user is None:
        return _no_access(request)

    clean_period = _period(period)
    snapshot = await run_in_threadpool(
        _build_policy_aware_operations_snapshot,
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
    user = _admin(request)
    if user is None:
        return _no_access(request)

    clean_period = _period(period)
    clean_question = str(question or "").strip()[:1200]

    snapshot = await run_in_threadpool(
        _build_policy_aware_operations_snapshot,
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
