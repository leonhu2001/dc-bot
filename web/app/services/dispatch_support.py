from __future__ import annotations

import json

from sqlalchemy.orm import Session

from shared.models import SyncEventType, WebOrder
from shared.order_acceptance import (
    ACCEPTED_PENDING_PAY,
    WAITING_ACCEPTANCE,
    claim_acceptance_order,
)
from web.app.services.admin_service import (
    add_worker_to_order,
    write_admin_audit_log,
)
from web.app.services.order_service import create_sync_event
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
)


PREPAY_STATUSES = {
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
}


def can_manage_dispatch_orders(user: dict | None) -> bool:
    user = user or {}
    return bool(
        user.get("is_admin")
        or user.get("is_customer_service")
        or user.get("is_manager")
    )


def _member_role_ids(member) -> list[str]:
    try:
        parsed = json.loads(str(getattr(member, "roles_json", "") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = []

    if not isinstance(parsed, list):
        return []

    return [
        str(role_id)
        for role_id in parsed
        if str(role_id).strip()
    ]


def assign_companion_from_dispatch(
    db: Session,
    *,
    order_id: int,
    companion_discord_id: str,
    support_user: dict,
) -> str:
    if not can_manage_dispatch_orders(support_user):
        raise ValueError("你沒有客服派單操作權限。")

    order = db.get(WebOrder, int(order_id))
    if order is None:
        raise ValueError("找不到這張訂單。")

    companion_id = str(companion_discord_id or "").strip()
    if not companion_id:
        raise ValueError("請選擇要指派的陪玩。")

    member = get_staff_member_by_id(
        db,
        discord_id=companion_id,
    )
    if member is None or not bool(getattr(member, "is_active", False)):
        raise ValueError("找不到這位陪玩，或該員工目前不是啟用狀態。")

    if not bool(getattr(member, "is_companion", False)):
        raise ValueError("客服快速指派目前只顯示並允許陪玩身分。")

    companion_name = get_staff_display_name(member)
    order_status = str(getattr(order, "status", "") or "").strip()

    if order_status in PREPAY_STATUSES:
        role_ids = _member_role_ids(member)
        if not role_ids:
            raise ValueError("這位陪玩的 Discord 身分組資料尚未同步，請稍後再試。")

        state = claim_acceptance_order(
            order_id=int(order_id),
            staff_discord_id=companion_id,
            staff_display_name=companion_name,
            staff_role_ids=role_ids,
            source="web_support",
        )

        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_CLAIMED,
            order_id=int(order_id),
            payload={
                "order_id": int(order_id),
                "worker_discord_id": companion_id,
                "worker_display_name": companion_name,
                "source": "web_support",
                "prepay_acceptance": True,
                "accepted_count": state.accepted_count,
                "required_staff_count": state.required_staff_count,
                "status": state.status,
                "admin_discord_id": str(support_user.get("id") or ""),
            },
        )
        write_admin_audit_log(
            db,
            admin_user=support_user,
            action="dispatch_support_assign_companion",
            target_type="web_order",
            target_id=str(order_id),
            after={
                "order_id": int(order_id),
                "worker_discord_id": companion_id,
                "worker_display_name": companion_name,
                "accepted_count": state.accepted_count,
                "required_staff_count": state.required_staff_count,
                "source": "web_support",
            },
        )
        db.commit()
        return (
            f"已指派 {companion_name}（"
            f"{state.accepted_count}/{state.required_staff_count}）。"
        )

    if order_status == "active":
        add_worker_to_order(
            db,
            order_id=int(order_id),
            worker_discord_id=companion_id,
            worker_display_name=companion_name,
            admin_user=support_user,
            reason="客服於接單大廳快速指派陪玩",
        )
        return f"已指派 {companion_name}。"

    raise ValueError("這張訂單目前的狀態不能再指派陪玩。")
