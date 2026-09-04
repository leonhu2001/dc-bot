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


ACTION_LABELS = {
    "order_workspace_edit": "??????",
    "set_customer_service_for_order": "??????",
    "toggle_named_bonus": "??????",
    "remove_worker_from_order": "??????",
    "add_worker_to_order": "??????",
    "set_manual_worker_payout": "??????",
    "set_worker_payout_status": "????????",
    "set_customer_service_payout_status": "????????",
}


TARGET_TYPE_LABELS = {
    "order": "??",
    "web_order": "??",
    "order_assignment": "????",
    "worker_payout": "????",
    "worker_payout_override": "??????",
    "customer_service_payout": "????",
}


FIELD_LABELS = {
    "id": "ID",
    "order_id": "?? ID",
    "order_no": "????",

    "customer_discord_id": "?? Discord ID",
    "customer_display_name": "????",

    "customer_service_discord_id": "?? Discord ID",
    "customer_service_display_name": "????",

    "category": "????",
    "item": "????",
    "quantity": "??",
    "amount": "????",
    "customer_pay_amount": "??????",
    "payment_method": "????",
    "status": "????",

    "closed_date": "????",
    "created_at": "????",
    "updated_at": "????",

    "assignment_id": "???? ID",
    "worker_discord_id": "???? Discord ID",
    "worker_display_name": "????",

    "is_active": "????",
    "has_named_bonus": "????",

    "payout_id": "???? ID",
    "manual_final_payout": "??????",
    "payout_status": "????",
    "paid_at": "????",

    "attention_reason": "????",
    "internal_note": "????",
    "extra_requirements": "????",
    "reason": "????",

    "ticket_channel_id": "???? ID",
    "dispatch_channel_id": "???? ID",
    "dispatch_message_id": "???? ID",
}


ORDER_STATUS_LABELS = {
    "pending_cs_dispatch": "??????",
    "waiting_acceptance": "??????",
    "accepted_pending_pay": "????????",
    "created": "???",
    "paid": "???",
    "active": "???",
    "stored": "??",
    "completed": "???",
    "done": "???",
    "closed": "???",
    "cancelled": "???",
    "canceled": "???",
}


PAYOUT_STATUS_LABELS = {
    "paid": "???",
    "unpaid": "???",
}


PAYMENT_METHOD_LABELS = {
    "wallet": "??",
    "bank_transfer": "????",
    "transfer": "??",
    "cash": "??",
}


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def label_action(value: str | None) -> str:
    if not value:
        return "????"

    return ACTION_LABELS.get(
        str(value),
        str(value).replace("_", " "),
    )


def label_target_type(value: str | None) -> str:
    if not value:
        return "????"

    return TARGET_TYPE_LABELS.get(
        str(value),
        str(value).replace("_", " "),
    )


def label_field(value: str) -> str:
    return FIELD_LABELS.get(
        str(value),
        str(value).replace("_", " "),
    )


def format_audit_value(key: str, value) -> str:
    if value is None:
        return "?"

    if isinstance(value, bool):
        return "?" if value else "?"

    if key == "status":
        return ORDER_STATUS_LABELS.get(str(value), str(value))

    if key == "payout_status":
        return PAYOUT_STATUS_LABELS.get(str(value), str(value))

    if key == "payment_method":
        return PAYMENT_METHOD_LABELS.get(str(value), str(value))

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", "?"),
        )

    if value == "":
        return "???"

    return str(value)


def format_audit_json(value: str | None) -> str:
    if not value:
        return "???"

    try:
        parsed = json.loads(value)
    except Exception:
        return str(value)

    if isinstance(parsed, dict):
        lines = []

        for key, item in parsed.items():
            lines.append(
                f"{label_field(str(key))}?"
                f"{format_audit_value(str(key), item)}"
            )

        return "\n".join(lines) if lines else "???"

    if isinstance(parsed, list):
        if not parsed:
            return "???"

        return "\n".join(
            f"? {format_audit_value('', item)}"
            for item in parsed
        )

    return str(parsed)


def format_datetime(value) -> str:
    if not value:
        return "-"

    try:
        return value.strftime("%Y/%m/%d %H:%M:%S")
    except Exception:
        return str(value)


@router.get("/admin/audit")
async def admin_audit_logs(
    request: Request,
    action: str | None = None,
    admin_id: str | None = None,
):
    user = get_current_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "????",
                "message": "???? Discord ???",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "????",
                "message": "??????????",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        statement = (
            select(AdminAuditLog)
            .order_by(AdminAuditLog.created_at.desc())
        )

        if action:
            statement = statement.where(
                AdminAuditLog.action == action
            )

        if admin_id:
            statement = statement.where(
                AdminAuditLog.admin_discord_id == admin_id
            )

        logs = list(
            db.scalars(
                statement.limit(300)
            ).all()
        )

        actions = [
            row[0]
            for row in db.execute(
                select(AdminAuditLog.action)
                .distinct()
                .order_by(AdminAuditLog.action.asc())
            ).all()
        ]

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_audit.html",
        context={
            "title": "????",
            "user": user,
            "logs": logs,
            "actions": actions,
            "selected_action": action or "",
            "admin_id": admin_id or "",
            "label_action": label_action,
            "label_target_type": label_target_type,
            "format_audit_json": format_audit_json,
            "format_datetime": format_datetime,
        },
    )
