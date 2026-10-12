from pathlib import Path
import json
import sqlite3
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, SyncEventType
from shared.order_acceptance import (
    PREPAY_ACCEPTANCE_STATUSES,
    claim_acceptance_order,
    get_acceptance_state,
    unclaim_acceptance_order,
)
from shared.order_state import (
    CANCELLED,
    CANCELLATION_REASON_LABELS,
    normalize_cancellation_reason_code,
    normalize_order_status,
    record_order_cancellation_in_connection,
    transition_order_state_in_connection,
)
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.order_service import (
    create_demo_orders_if_empty,
    create_sync_event,
    list_admin_orders,
)
from web.app.services.order_financial_edit import (
    preserve_order_financial_gaps,
)
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
    sync_staff_members_from_discord,
)
from core.time_utils import (
    format_taipei_datetime_from_utc,
    get_taipei_date_from_utc,
    get_taipei_now,
)

from web.app.routers.admin_common import (
    dedupe_admin_worker_members,
    get_current_user,
    list_admin_worker_dropdown_members,
    redirect_to_admin,
    require_admin_user,
)

router = APIRouter(tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.post("/admin/orders/{order_id}/cancel")
async def admin_cancel_order(
    order_id: int,
    request: Request,
    cancellation_reason_code: str = Form(default="unspecified"),
    cancellation_reason_text: str = Form(default=""),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    reason_code = normalize_cancellation_reason_code(
        cancellation_reason_code
    )
    reason_text = str(cancellation_reason_text or "").strip()

    if reason_code == "unspecified":
        return redirect_to_admin(error="取消訂單前請先選擇取消原因。")

    db = SessionLocal()

    try:
        row = db.execute(
            text(
                "SELECT id, status FROM web_orders "
                "WHERE id = :order_id"
            ),
            {"order_id": order_id},
        ).mappings().first()

        if row is None:
            return redirect_to_admin(error="找不到這筆訂單。")

        transition_order_state_in_connection(
            db.connection(),
            order_id=int(order_id),
            target_status=CANCELLED,
            source="admin_cancel",
            reason=reason_text or CANCELLATION_REASON_LABELS[reason_code],
            actor_discord_id=user.get("id"),
            cancellation_reason_code=reason_code,
            cancellation_reason_text=reason_text,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return redirect_to_admin(error=f"取消訂單失敗：{exc}")
    except Exception as exc:
        db.rollback()
        return redirect_to_admin(error=f"取消訂單失敗：{exc}")
    finally:
        db.close()

    return redirect_to_admin(message="訂單已取消，取消原因已記錄。")


@router.post("/admin/staff/sync")
async def admin_sync_staff(request: Request):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(
            url="/admin/staff-center?"
            + urlencode({"error": "你沒有客服後台權限，或登入狀態已過期。"}),
            status_code=303,
        )

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
        db.commit()
        message = (
            result.get("message")
            or (
                "成員同步完成：掃描 "
                f"{result.get('total_seen', result.get('scanned', '?'))} 人，"
                f"寫入 {result.get('synced_count', result.get('written', '?'))} 人。"
            )
        )
        query = urlencode({"message": message})
    except Exception as e:
        db.rollback()
        query = urlencode({"error": f"同步成員失敗：{e}"})
    finally:
        db.close()

    return RedirectResponse(
        url=f"/admin/staff-center?{query}",
        status_code=303,
    )


@router.post("/admin/orders/{order_id}/customer-service")
async def admin_set_customer_service(
    request: Request,
    order_id: int,
    customer_service_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=customer_service_discord_id)
        customer_service_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else customer_service_discord_id
        )

        set_customer_service_for_order(
            db,
            order_id=order_id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已更新此單對接客服，客服 5% 分潤已重新計算。")


@router.post("/admin/assignments/{assignment_id}/named-bonus")
async def update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        toggle_named_bonus_for_assignment(
            db,
            assignment_id=assignment_id,
            enabled=enabled == "on",
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="掛名加成已更新。")


@router.post("/admin/assignments/{assignment_id}/remove")
async def admin_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        remove_worker_from_order(
            db,
            assignment_id=assignment_id,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已移除這位護航 / 陪玩，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/add-worker")
async def admin_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=worker_discord_id)
        worker_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else worker_discord_id
        )

        add_worker_to_order(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已新增/更換護航 / 陪玩，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/manual-payout")
async def admin_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_manual_worker_payout(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            manual_final_payout=manual_final_payout,
            reason=reason,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已手動更新護航 / 陪玩分潤金額。")


@router.post("/admin/worker-payouts/{payout_id}/status")
async def admin_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="護航 / 陪玩分潤狀態已更新。")


@router.post("/admin/customer-service-payouts/{payout_id}/status")
async def admin_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_customer_service_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="魔丸♫魔丸♫客服分潤狀態已更新。")

# MAWAN PHASE 4A-2R6 ORDER WORKSPACE


# Keep route registration stable for web.app.main while implementation lives by responsibility.
from web.app.routers.admin_dashboard import router as admin_dashboard_router
from web.app.routers.admin_order_workspace import router as admin_order_workspace_router

router.include_router(admin_dashboard_router)
router.include_router(admin_order_workspace_router)
