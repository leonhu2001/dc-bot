from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select

from shared.db import SessionLocal
from shared.models import AdminAuditLog, WebUser
from shared.staff_models import WebStaffMember


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
    "accounting_recalculate_unpaid_payouts": "帳務修復｜重算未發放分潤",
    "accounting_void_cancelled_payouts": "帳務修復｜取消單分潤 void",
    "accounting_queue_wallet_reconciliation": "帳務修復｜排入錢包差額修復",
    "accounting_recognize_historical_discount": "帳務修復｜認列歷史折扣",
    "cancel_order": "取消訂單",
    "sync_staff_members": "同步人員名單",
    "update_order_internal_note": "更新客服內部備註",
    "update_order_attention": "更新訂單注意標記",
    "approve_payment_review": "核准付款",
    "reject_payment_review": "駁回付款",
    "retry_payment_review_apply": "重新套用付款結果",
    "approve_topup": "核准儲值",
    "reject_topup": "駁回儲值",
    "bulk_mark_payouts_paid": "批次標記薪資已發放",
    "bulk_mark_payouts_unpaid": "批次改回薪資未發放",
    "set_person_payout_status": "更新單一人員薪資狀態",
    "update_staff_profile": "編輯成員個人牆",
    "toggle_staff_profile_public": "切換成員個人牆公開狀態",
    "toggle_review_hidden": "切換評價隱藏狀態",
    "toggle_review_public": "切換評價公開狀態",
    "admin_claim_prepay_acceptance": "人工補登付款前接單",
    "admin_unclaim_prepay_acceptance": "人工移除付款前接單",
}


TARGET_TYPE_LABELS = {
    "order": "訂單",
    "web_order": "訂單",
    "order_assignment": "接單紀錄",
    "worker_payout": "人員分潤",
    "worker_payout_override": "人員分潤調整",
    "customer_service_payout": "客服分潤",
    "payment_review": "付款審核",
    "topup_order": "儲值單",
    "payout_summary": "薪資批次",
    "payout_person": "人員薪資",
    "staff_profile": "成員個人牆",
    "staff_directory": "人員名單",
    "order_review": "評價",
    "order_acceptance": "付款前接單",
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
    "operator": "操作人員",
    "payout_state": "分潤快照",
    "historical_discount_amount": "歷史折扣",

    "attention_reason": "注意事項",
    "internal_note": "內部備註",
    "extra_requirements": "額外需求",
    "review_no": "付款單號",
    "source_type": "付款來源",
    "source_id": "來源 ID",
    "approved_at": "核准時間",
    "approved_by_discord_id": "核准人員 ID",
    "approved_by_display_name": "核准人員",
    "rejected_at": "駁回時間",
    "rejected_by_discord_id": "駁回人員 ID",
    "rejected_by_display_name": "駁回人員",
    "rejected_reason": "駁回原因",
    "apply_error": "套用錯誤",
    "topup_no": "儲值單號",
    "credited_amount": "實際入帳",
    "vip_level_before": "原 VIP",
    "vip_level_after": "新 VIP",
    "rebate_amount": "回饋金額",
    "total_amount": "總金額",
    "count": "筆數",
    "rows": "受影響明細",
    "person_id": "人員 ID",
    "person_name": "人員名稱",
    "display_name": "顯示名稱",
    "profile_type": "個人牆類型",
    "role_title": "階級 / 職位",
    "main_games": "主要遊戲",
    "service_tags": "服務項目",
    "bio": "個人介紹",
    "card_image_url": "名片圖片",
    "is_public": "是否公開",
    "is_hidden": "是否隱藏",
    "_actor_display_name": "操作人員名稱",
    "accepted_count": "已接人數",
    "required_staff_count": "需求人數",
    "staff_ids": "接單人員 ID",
    "removed_staff_discord_id": "移除人員 Discord ID",
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
    "void": "作廢",
}


MONEY_ACTIONS = {
    "set_manual_worker_payout",
    "set_worker_payout_status",
    "set_customer_service_payout_status",
    "approve_payment_review",
    "reject_payment_review",
    "retry_payment_review_apply",
    "approve_topup",
    "reject_topup",
    "bulk_mark_payouts_paid",
    "bulk_mark_payouts_unpaid",
    "set_person_payout_status",
    "accounting_recalculate_unpaid_payouts",
    "accounting_void_cancelled_payouts",
    "accounting_queue_wallet_reconciliation",
    "accounting_recognize_historical_discount",
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


def _preferred_operator_name(
    *,
    display_name: str | None = None,
    global_name: str | None = None,
    username: str | None = None,
    discord_id: str | None = None,
) -> str:
    return str(
        display_name
        or global_name
        or username
        or discord_id
        or "未知人員"
    )


def build_operator_name_map(db, discord_ids) -> dict[str, str]:
    ids = {
        str(item).strip()
        for item in (discord_ids or [])
        if str(item).strip()
    }

    if not ids:
        return {}

    result: dict[str, str] = {}

    staff_rows = list(
        db.scalars(
            select(WebStaffMember)
            .where(WebStaffMember.discord_id.in_(ids))
        ).all()
    )

    for member in staff_rows:
        discord_id = str(member.discord_id)
        result[discord_id] = _preferred_operator_name(
            display_name=member.display_name,
            global_name=member.global_name,
            username=member.username,
            discord_id=discord_id,
        )

    missing_ids = ids - set(result)

    if missing_ids:
        user_rows = list(
            db.scalars(
                select(WebUser)
                .where(WebUser.discord_id.in_(missing_ids))
            ).all()
        )

        for member in user_rows:
            discord_id = str(member.discord_id)
            result[discord_id] = _preferred_operator_name(
                global_name=member.global_name,
                username=member.username,
                discord_id=discord_id,
            )

    return result


@router.get("/admin/audit")
async def admin_audit_logs(
    request: Request,
    action: str | None = None,
    admin_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    q: str | None = None,
    money_only: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
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

        if target_type:
            statement = statement.where(
                AdminAuditLog.target_type == target_type
            )

        if target_id:
            statement = statement.where(
                AdminAuditLog.target_id == target_id
            )

        keyword = str(q or "").strip()
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                or_(
                    AdminAuditLog.action.like(like),
                    AdminAuditLog.target_type.like(like),
                    AdminAuditLog.target_id.like(like),
                    AdminAuditLog.admin_discord_id.like(like),
                    AdminAuditLog.before_json.like(like),
                    AdminAuditLog.after_json.like(like),
                )
            )

        if str(money_only or "").strip() in {"1", "true", "on", "yes"}:
            statement = statement.where(
                AdminAuditLog.action.in_(MONEY_ACTIONS)
            )

        try:
            if date_from:
                statement = statement.where(
                    AdminAuditLog.created_at >= datetime.fromisoformat(date_from)
                )
        except ValueError:
            pass

        try:
            if date_to:
                end_value = datetime.fromisoformat(date_to)
                end_value = end_value.replace(hour=23, minute=59, second=59)
                statement = statement.where(
                    AdminAuditLog.created_at <= end_value
                )
        except ValueError:
            pass

        logs = list(
            db.scalars(statement.limit(300)).all()
        )

        operator_names = build_operator_name_map(
            db,
            {
                str(log.admin_discord_id)
                for log in logs
                if str(log.admin_discord_id or "").strip()
            },
        )

        actions = [
            row[0]
            for row in db.execute(
                select(AdminAuditLog.action)
                .distinct()
                .order_by(AdminAuditLog.action.asc())
            ).all()
        ]

        target_types = [
            row[0]
            for row in db.execute(
                select(AdminAuditLog.target_type)
                .distinct()
                .order_by(AdminAuditLog.target_type.asc())
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
            "target_types": target_types,
            "selected_target_type": target_type or "",
            "target_id": target_id or "",
            "q": q or "",
            "money_only": str(money_only or "") in {"1", "true", "on", "yes"},
            "date_from": date_from or "",
            "date_to": date_to or "",
            "label_action": label_action,
            "label_target_type": label_target_type,
            "format_audit_json": format_audit_json,
            "format_datetime": format_datetime,
            "operator_names": operator_names,
        },
    )