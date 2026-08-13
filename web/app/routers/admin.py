from pathlib import Path
import sqlite3
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.order_service import create_demo_orders_if_empty, list_admin_orders
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
    sync_staff_members_from_discord,
)

router = APIRouter(tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_admin(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin", status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user



def dedupe_admin_worker_members(members):
    """Admin 首頁新增 / 更換打手下拉：打手或陪玩都顯示，同一人只出現一次。"""
    result = {}
    for member in members or []:
        discord_id = str(getattr(member, "discord_id", "") or member.get("discord_id", "") if isinstance(member, dict) else getattr(member, "discord_id", "")).strip()
        if not discord_id:
            continue

        is_worker = bool(getattr(member, "is_worker", False) if not isinstance(member, dict) else member.get("is_worker"))
        is_companion = bool(getattr(member, "is_companion", False) if not isinstance(member, dict) else member.get("is_companion"))

        if not (is_worker or is_companion):
            continue

        result[discord_id] = member

    def member_name(member):
        if isinstance(member, dict):
            return str(member.get("display_name") or member.get("username") or member.get("discord_id") or "")
        return str(getattr(member, "display_name", "") or getattr(member, "username", "") or getattr(member, "discord_id", ""))

    return sorted(result.values(), key=member_name)


def list_admin_worker_dropdown_members() -> list[dict]:
    """Admin 首頁新增 / 更換打手下拉。

    只要有打手或陪玩身分就顯示；同一人只出現一次。
    """
    db_path = Path(__file__).resolve().parents[3] / "web_dashboard.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                discord_id,
                username,
                display_name,
                global_name,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            FROM web_staff_members
            WHERE COALESCE(is_active, 1) = 1
              AND (
                    COALESCE(is_worker, 0) = 1
                 OR COALESCE(is_companion, 0) = 1
              )
            ORDER BY
                COALESCE(display_name, ''),
                COALESCE(global_name, ''),
                COALESCE(username, ''),
                discord_id
            """
        ).fetchall()

        members = []
        seen = set()

        for row in rows:
            discord_id = str(row["discord_id"] or "").strip()
            if not discord_id or discord_id in seen:
                continue

            seen.add(discord_id)

            members.append({
                "discord_id": discord_id,
                "username": row["username"],
                "display_name": row["display_name"],
                "global_name": row["global_name"],
                "is_worker": bool(row["is_worker"]),
                "is_companion": bool(row["is_companion"]),
                "is_customer_service": bool(row["is_customer_service"]),
                "is_active": bool(row["is_active"]),
            })

        return members

    finally:
        conn.close()

@router.get("/admin")
async def admin_dashboard(
    request: Request,
    message: str | None = None,
    error: str | None = None,
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
                "message": "你沒有總控後台權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        create_demo_orders_if_empty(db)
        orders = [
            order
            for order in list_admin_orders(db)
            if str(getattr(order, "status", "") or "").lower() not in {"cancelled", "canceled"}
        ]
        customer_service_members = list_customer_service_members(db)
        worker_members = list_admin_worker_dropdown_members()

        customer_service_payout_rows = list(
            db.scalars(
                select(CustomerServicePayout).order_by(CustomerServicePayout.id.asc())
            ).all()
        )

        customer_service_payouts_by_order: dict[int, list[CustomerServicePayout]] = {}

        for payout in customer_service_payout_rows:
            customer_service_payouts_by_order.setdefault(payout.order_id, []).append(payout)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "title": "總控後台",
            "user": user,
            "orders": orders,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "customer_service_payouts_by_order": customer_service_payouts_by_order,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "message": message,
            "error": error,
        },
    )



@router.post("/admin/orders/{order_id}/cancel")
async def admin_cancel_order(
    order_id: int,
    request: Request,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    db = SessionLocal()

    try:
        row = db.execute(
            text("SELECT id FROM web_orders WHERE id = :order_id"),
            {"order_id": order_id},
        ).fetchone()

        if row is None:
            return redirect_to_admin(error="找不到這筆訂單。")

        db.execute(
            text("UPDATE web_orders SET status = 'cancelled' WHERE id = :order_id"),
            {"order_id": order_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return redirect_to_admin(error=f"取消訂單失敗：{exc}")
    finally:
        db.close()

    return redirect_to_admin(message="訂單已取消，已從總控列表隱藏。")


@router.post("/admin/staff/sync")
async def admin_sync_staff(request: Request):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
    except Exception as e:
        db.rollback()
        return redirect_to_admin(error=f"同步成員失敗：{e}")
    finally:
        db.close()

    return redirect_to_admin(
        message=result.get("message") or f"成員同步完成：掃描 {result.get('total_seen', result.get('scanned', '?'))} 人，寫入 {result.get('synced_count', result.get('written', '?'))} 人。"
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
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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

    return redirect_to_admin(message="已移除這位打手，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/add-worker")
async def admin_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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

    return redirect_to_admin(message="已新增/更換打手，分潤已重新計算。")


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
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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

    return redirect_to_admin(message="已手動更新打手分潤金額。")


@router.post("/admin/worker-payouts/{payout_id}/status")
async def admin_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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

    return redirect_to_admin(message="打手分潤狀態已更新。")


@router.post("/admin/customer-service-payouts/{payout_id}/status")
async def admin_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有總控後台權限，或登入狀態已過期。")

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

    return redirect_to_admin(message="客服分潤狀態已更新。")
