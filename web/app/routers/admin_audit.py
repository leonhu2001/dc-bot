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
    "order_workspace_edit": "編輯訂單資料",
    "set_customer_service_for_order": "指定訂單客服",
    "toggle_named_bonus": "切換指定加成",
    "remove_worker_from_order": "移除接單人員",
    "add_worker_to_order": "新增接單人員",
    "set_manual_worker_payout": "調整人員分潤",
    "set_worker_payout_status": "更新人員分潤狀態",
    "set_customer_service_payout_status": "更新客服分潤狀態",
}


TARGET_TYPE_LABELS = {
    "order": "訂單",
    "web_order": "訂單",
    "order_assignment": "接單紀錄",
    "worker_payout": "人員分潤",
    "worker_payout_override": "人員分潤調整",
    "customer_service_payout": "客服分潤",
}


FIELD_LABELS = {
    "id": "ID",
    "order_id": "訂單 ID",
    "bot_order_no": "訂單編號",

    "ticket_channel_id": "票口頻道 ID",
    "dispatch_channel_id": "派單頻道 ID",
    "dispatch_message_id": "派單訊息 ID",

    "customer_discord_id": "顧客 Discord ID",
    "customer_display_name": "顧客名稱",

    "customer_service_discord_id": "客服 Discord ID",
    "customer_service_display_name": "客服名稱",

    "category": "服務分類",
    "item": "服務項目",
    "quantity": "數量",

    "amount": "訂單金額",
    "original_amount": "原始金額",
    "payout_base_amount": "分潤計算金額",
    "customer_pay_amount": "顧客實付金額",

    "manual_discount_amount": "手動折扣",
    "cash_coupon_amount": "現金券折抵",
    "store_absorbed_amount": "店家吸收金額",

    "payment_method": "付款方式",
    "status": "訂單狀態",

    "order_rule_key": "計價規則",
    "rule_version": "規則版本",
    "rule_snapshot_json": "規則快照",
    "price_snapshot_json": "價格快照",

    "note": "備註",
    "reason": "操作原因",

    "created_at": "建立時間",
    "updated_at": "更新時間",
    "closed_date": "結案日期",

    "assignment_id": "接單紀錄 ID",
    "worker_discord_id": "接單人員 Discord ID",
    "worker_display_name": "接單人員",

    "is_active": "是否有效",
    "has_named_bonus": "指定加成",

    "payout_id": "分潤紀錄 ID",
    "manual_final_payout": "手動最終分潤",
    "payout_status": "發放狀態",
    "paid_at": "發放時間",

    "attention_reason": "注意事項",
    "internal_note": "內部備註",
    "extra_requirements": "額外需求",
}


ORDER_STATUS_LABELS = {
    "pending_cs_dispatch": "等待客服派單",
    "waiting_acceptance": "等待接單確認",
    "accepted_pending_pay": "已接單／等待付款",
    "created": "已建立",
    "paid": "已付款",
    "active": "進行中",
    "stored": "存單",
    "completed": "已完成",
    "done": "已完成",
    "closed": "已結單",
    "cancelled": "已取消",
    "canceled": "已取消",
}


PAYOUT_STATUS_LABELS = {
    "paid": "已發放",
    "unpaid": "未發放",
}


PAYMENT_METHOD_LABELS = {
    "wallet": "錢包",
    "bank_transfer": "銀行轉帳",
    "transfer": "轉帳",
    "cash": "現金",
}


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def label_action(value: str | None) -> str:
    if not value:
        return "未知操作"

    return ACTION_LABELS.get(str(value), str(value))


def label_target_type(value: str | None) -> str:
    if not value:
        return "未知對象"

    return TARGET_TYPE_LABELS.get(str(value), str(value))


def label_field(value: str) -> str:
    return FIELD_LABELS.get(str(value), str(value))


def format_audit_value(key: str, value) -> str:
    if value is None:
        return "無"

    if isinstance(value, bool):
        return "是" if value else "否"

    if value == "":
        return "未填寫"

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
            indent=2,
        )

    return str(value)


def format_audit_json(value: str | None) -> str:
    if not value:
        return "無資料"

    try:
        parsed = json.loads(value)
    except Exception:
        return str(value)

    if not isinstance(parsed, dict):
        return format_audit_value("", parsed)

    lines = []

    for key, item in parsed.items():
        lines.append(
            f"{label_field(str(key))}："
            f"{format_audit_value(str(key), item)}"
        )

    return "\n".join(lines) if lines else "無資料"


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
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
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
            db.scalars(statement.limit(300)).all()
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
            "title": "操作紀錄",
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