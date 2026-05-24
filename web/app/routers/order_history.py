import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, OrderAssignment, OrderStatus, PayoutStatus, WebOrder
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
)

router = APIRouter(tags=["order-history"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def redirect_to_history(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin/orders/history?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin/orders/history", status_code=303)


def list_history_orders(
    *,
    status_filter: str = "all",
    keyword: str | None = None,
) -> list[WebOrder]:
    db = SessionLocal()

    try:
        statement = (
            select(WebOrder)
            .where(WebOrder.status != OrderStatus.ACTIVE.value)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
            .order_by(WebOrder.updated_at.desc(), WebOrder.created_at.desc())
        )

        if status_filter and status_filter != "all":
            statement = statement.where(WebOrder.status == status_filter)

        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            statement = statement.where(
                WebOrder.bot_order_no.like(like_keyword)
                | WebOrder.customer_display_name.like(like_keyword)
                | WebOrder.customer_discord_id.like(like_keyword)
                | WebOrder.category.like(like_keyword)
                | WebOrder.item.like(like_keyword)
            )

        return list(db.scalars(statement).all())
    finally:
        db.close()




def build_customer_groups(orders):
    """依老闆 Discord ID 分組；同 ID 有名稱就補給只有 ID 的舊單。"""
    name_by_customer_id = {}

    for order in orders:
        customer_id = str(getattr(order, "customer_discord_id", "") or "").strip()
        customer_name = str(getattr(order, "customer_display_name", "") or "").strip()

        if customer_id and customer_name and customer_name != customer_id:
            name_by_customer_id[customer_id] = customer_name

    groups_by_key = {}

    for order in orders:
        customer_id = str(getattr(order, "customer_discord_id", "") or "").strip()
        raw_name = str(getattr(order, "customer_display_name", "") or "").strip()

        key = customer_id or raw_name or "unknown"
        display_name = raw_name or name_by_customer_id.get(customer_id) or customer_id or "未知老闆"

        if customer_id and customer_id in name_by_customer_id:
            display_name = name_by_customer_id[customer_id]

        if key not in groups_by_key:
            groups_by_key[key] = {
                "customer_id": customer_id,
                "customer_name": display_name,
                "orders": [],
                "order_count": 0,
                "total_amount": 0,
            }

        group = groups_by_key[key]
        group["orders"].append(order)
        group["order_count"] += 1
        group["total_amount"] += int(getattr(order, "amount", 0) or 0)

        if group["customer_name"] == group["customer_id"] and display_name:
            group["customer_name"] = display_name

    groups = list(groups_by_key.values())
    groups.sort(key=lambda group: (str(group["customer_name"] or ""), str(group["customer_id"] or "")))
    return groups




def get_history_db_path() -> str:
    return str(Path.cwd() / "web_dashboard.db")


def fetch_history_payouts(order_ids: list[int]) -> dict[int, list[dict]]:
    """抓歷史訂單的打手/客服分潤，給歷史頁批量修改用。"""
    if not order_ids:
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    result: dict[int, list[dict]] = {}

    conn = sqlite3.connect(get_history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        worker_rows = conn.execute(
            f"""
            SELECT
                id,
                order_id,
                worker_discord_id AS person_id,
                worker_display_name AS person_name,
                final_payout AS amount,
                payout_status
            FROM worker_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in worker_rows:
            order_id = int(row["order_id"])
            result.setdefault(order_id, []).append(
                {
                    "kind": "worker",
                    "label": "打手",
                    "id": int(row["id"]),
                    "person_id": row["person_id"],
                    "person_name": row["person_name"] or row["person_id"],
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "input_name": f"worker_payout_{int(row['id'])}",
                }
            )

        cs_rows = conn.execute(
            f"""
            SELECT
                id,
                order_id,
                customer_service_discord_id AS person_id,
                customer_service_display_name AS person_name,
                payout_amount AS amount,
                payout_status
            FROM customer_service_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in cs_rows:
            order_id = int(row["order_id"])
            result.setdefault(order_id, []).append(
                {
                    "kind": "customer_service",
                    "label": "客服",
                    "id": int(row["id"]),
                    "person_id": row["person_id"],
                    "person_name": row["person_name"] or row["person_id"],
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "input_name": f"cs_payout_{int(row['id'])}",
                }
            )
    finally:
        conn.close()

    return result


def to_int(value, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return default


def safe_status(value: str | None) -> str:
    value = (value or "").strip()

    if value in {"active", "stored", "closed"}:
        return value

    return "closed"


@router.get("/admin/orders/history")
async def admin_order_history(
    request: Request,
    status: str = "all",
    keyword: str | None = None,
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
        orders = list_history_orders(status_filter=status, keyword=keyword)
        customer_service_members = list_customer_service_members(db)
        worker_members = list_worker_members(db)

        order_ids = [order.id for order in orders]
        customer_service_payouts_by_order: dict[int, list[CustomerServicePayout]] = {}

        if order_ids:
            service_payouts = list(
                db.scalars(
                    select(CustomerServicePayout)
                    .where(CustomerServicePayout.order_id.in_(order_ids))
                    .order_by(CustomerServicePayout.id.asc())
                ).all()
            )

            for payout in service_payouts:
                customer_service_payouts_by_order.setdefault(payout.order_id, []).append(payout)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="order_history.html",
        context={
            "title": "歷史訂單",
            "user": user,
            "orders": orders,
            "customer_groups": build_customer_groups(orders),
            "payouts_by_order_id": fetch_history_payouts([int(order.id) for order in orders]),
            "current_status": status,
            "keyword": keyword or "",
            "message": message,
            "error": error,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "customer_service_payouts_by_order": customer_service_payouts_by_order,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "status_options": [
                ("all", "全部"),
                (OrderStatus.CLOSED.value, "已結單"),
                (OrderStatus.STORED.value, "存單"),
                (OrderStatus.CANCELLED.value, "取消"),
            ],
        },
    )


@router.post("/admin/orders/history/{order_id}/customer-service")
async def history_set_customer_service(
    request: Request,
    order_id: int,
    customer_service_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已更新歷史訂單對接客服，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/add-worker")
async def history_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已新增歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/assignments/{assignment_id}/named-bonus")
async def history_update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="歷史訂單掛名加成已更新。")


@router.post("/admin/orders/history/assignments/{assignment_id}/remove")
async def history_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已移除歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/manual-payout")
async def history_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已手動更新歷史訂單分潤。")


@router.post("/admin/orders/history/worker-payouts/{payout_id}/status")
async def history_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(db, payout_id=payout_id, status=status, admin_user=user)
    except ValueError as e:
        db.rollback()
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="打手/陪玩分潤狀態已更新。")


@router.post("/admin/orders/history/customer-service-payouts/{payout_id}/status")
async def history_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="客服分潤狀態已更新。")



@router.post("/admin/orders/history/bulk-update")
async def bulk_update_order_history(request: Request):
    user = request.session.get("user")

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    order_ids = [to_int(order_id) for order_id in form.getlist("order_id") if to_int(order_id) > 0]

    if not order_ids:
        return RedirectResponse(url="/admin/orders/history", status_code=303)

    conn = sqlite3.connect(get_history_db_path())

    try:
        for order_id in order_ids:
            category = str(form.get(f"category_{order_id}") or "").strip()
            item = str(form.get(f"item_{order_id}") or "").strip()
            amount = to_int(form.get(f"amount_{order_id}"), 0)
            status = safe_status(form.get(f"status_{order_id}"))
            customer_discord_id = str(form.get(f"customer_discord_id_{order_id}") or "").strip()
            customer_display_name = str(form.get(f"customer_display_name_{order_id}") or "").strip()

            conn.execute(
                """
                UPDATE web_orders
                SET
                    customer_discord_id = ?,
                    customer_display_name = ?,
                    category = ?,
                    item = ?,
                    amount = ?,
                    status = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    customer_discord_id,
                    customer_display_name,
                    category,
                    item,
                    amount,
                    status,
                    order_id,
                ),
            )

        conn.commit()
    finally:
        conn.close()

    # 先按訂單狀態與金額重新計算一次分潤。
    # active / stored 不產生分潤；closed 才會產生。
    except Exception as exc:
        print(f"[order-history] recalculate payouts failed: {exc}")

    # 再套用人工修改過的分潤金額。
    conn = sqlite3.connect(get_history_db_path())

    try:
        for key, value in form.multi_items():
            if key.startswith("worker_payout_"):
                payout_id = to_int(key.replace("worker_payout_", ""), 0)
                amount = to_int(value, 0)

                if payout_id > 0:
                    conn.execute(
                        """
                        UPDATE worker_payouts
                        SET
                            gross_share = ?,
                            base_payout = ?,
                            named_bonus_amount = 0,
                            final_payout = ?
                        WHERE id = ?
                        """,
                        (amount, amount, amount, payout_id),
                    )

            if key.startswith("cs_payout_"):
                payout_id = to_int(key.replace("cs_payout_", ""), 0)
                amount = to_int(value, 0)

                if payout_id > 0:
                    conn.execute(
                        """
                        UPDATE customer_service_payouts
                        SET payout_amount = ?
                        WHERE id = ?
                        """,
                        (amount, payout_id),
                    )

        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/orders/history", status_code=303)

