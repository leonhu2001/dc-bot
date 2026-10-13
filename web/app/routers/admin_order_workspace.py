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
from web.app.services.admin_order_workspace_data import (
    _mw4a2r6_cs_members,
    _mw4a2r6_ensure_meta_table,
    _mw4a2r6_load_order_bundle,
    _mw4a2r6_safe_int,
    _mw4a2r6_table_exists,
    _mw4a2r6_user_name,
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























def _mw4a2r6_redirect(
    order_id,
    *,
    request: Request | None = None,
    message=None,
    error=None,
):

    from urllib.parse import (
        urlencode,
    )


    params = {}


    if message:

        params[
            "message"
        ] = message


    if error:

        params[
            "error"
        ] = error


    if request is not None:
        return_to = str(
            request.query_params.get("return_to")
            or ""
        ).strip()

        if (
            return_to == "/admin"
            or return_to.startswith("/admin/")
        ):
            params["return_to"] = return_to


    base = (
        "/admin/order-workspace/"
        + str(
            int(
                order_id
            )
        )
    )


    if params:

        base += (
            "?"
            + urlencode(
                params
            )
        )


    return RedirectResponse(
        url=base,
        status_code=303,
    )


# BEGIN MAWAN_R8_ORDER_WORKSPACE

import re as _mw_r8_re


def _mw_r8_jsonable_row(row):
    if row is None:
        return None

    result = {}

    for key, value in dict(row).items():
        if value is not None and hasattr(value, "isoformat"):
            try:
                value = value.isoformat()
            except Exception:
                value = str(value)

        result[str(key)] = value

    return result


def _mw_r8_snapshot_payout_status(db, order_id: int) -> dict:
    snapshot = {
        "worker": {},
        "customer_service": {},
    }

    for row in db.execute(
        text(
            """
            SELECT
                worker_discord_id AS person_id,
                payout_status,
                paid_at
            FROM worker_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["worker"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    for row in db.execute(
        text(
            """
            SELECT
                customer_service_discord_id AS person_id,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["customer_service"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    return snapshot


def _mw_r8_restore_payout_status(db, order_id: int, snapshot: dict) -> None:
    for person_id, state in (snapshot.get("worker") or {}).items():
        db.execute(
            text(
                """
                UPDATE worker_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND worker_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )

    for person_id, state in (snapshot.get("customer_service") or {}).items():
        db.execute(
            text(
                """
                UPDATE customer_service_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND customer_service_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )


def _mw_r8_worker_rows(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                oa.id AS assignment_id,
                oa.worker_discord_id,
                oa.worker_display_name,
                oa.has_named_bonus,
                oa.is_active,
                wp.id AS payout_id,
                wp.gross_share,
                wp.base_payout,
                wp.named_bonus_amount,
                wp.final_payout,
                wp.payout_status,
                wp.paid_at
            FROM order_assignments oa
            LEFT JOIN worker_payouts wp
              ON wp.id = (
                    SELECT wp2.id
                    FROM worker_payouts wp2
                    WHERE wp2.order_id = oa.order_id
                      AND wp2.worker_discord_id = oa.worker_discord_id
                    ORDER BY wp2.id DESC
                    LIMIT 1
                )
            WHERE oa.order_id = :order_id
              AND COALESCE(oa.is_active, 1) = 1
            ORDER BY oa.id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return [dict(row) for row in rows]


def _mw_r8_cs_payout_rows(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                id,
                customer_service_discord_id,
                customer_service_display_name,
                rate,
                payout_amount,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            ORDER BY id DESC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return [dict(row) for row in rows]


@router.get("/admin/orders/history")
async def admin_order_history_redirect_r8(request: Request):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/order-workspace/{order_id}")
async def admin_order_workspace_r8(
    order_id: int,
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        order, customer_history, meta = _mw4a2r6_load_order_bundle(
            db,
            int(order_id),
        )

        if order is None:
            return RedirectResponse(
                url="/admin?error=%E6%89%BE%E4%B8%8D%E5%88%B0%E9%80%99%E7%AD%86%E8%A8%82%E5%96%AE",
                status_code=303,
            )

        financial = db.execute(
            text(
                """
                SELECT
                    closed_at,
                    updated_at,
                    amount,
                    customer_pay_amount,
                    original_amount,
                    payout_base_amount,
                    manual_discount_amount,
                    cash_coupon_amount,
                    store_absorbed_amount,
                    historical_discount_amount
                FROM web_orders
                WHERE id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).mappings().first()

        financial = dict(financial) if financial is not None else {}

        finalized_at = financial.get("closed_at")
        if (
            not finalized_at
            and str(order.get("status") or "").strip().lower()
            in {"closed", "completed", "done", "cancelled", "canceled"}
        ):
            # Historical final orders may predate closed_at-on-cancel. Display the best existing
            # timestamp without bulk-mutating old rows.
            finalized_at = financial.get("updated_at")
        order["closed_date"] = str(finalized_at or "")[:10]
        order["raw_amount"] = _mw4a2r6_safe_int(financial.get("amount"), 0)
        order["customer_pay_amount"] = _mw4a2r6_safe_int(
            financial.get("customer_pay_amount"),
            None,
        )
        order["original_amount"] = _mw4a2r6_safe_int(
            financial.get("original_amount"),
            None,
        )
        order["payout_base_amount"] = _mw4a2r6_safe_int(
            financial.get("payout_base_amount"),
            None,
        )
        order["manual_discount_amount"] = _mw4a2r6_safe_int(
            financial.get("manual_discount_amount"),
            0,
        ) or 0
        order["cash_coupon_amount"] = _mw4a2r6_safe_int(
            financial.get("cash_coupon_amount"),
            0,
        ) or 0
        order["store_absorbed_amount"] = _mw4a2r6_safe_int(
            financial.get("store_absorbed_amount"),
            0,
        ) or 0
        order["historical_discount_amount"] = _mw4a2r6_safe_int(
            financial.get("historical_discount_amount"),
            0,
        ) or 0

        customer_service_members = _mw4a2r6_cs_members(db)
        worker_members = list_admin_worker_dropdown_members()
        workspace_assignments = _mw_r8_worker_rows(db, int(order_id))
        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))

        acceptance_state = None
        if str(order.get("status") or "").strip().lower() in PREPAY_ACCEPTANCE_STATUSES:
            try:
                acceptance_state = get_acceptance_state(int(order_id))
            except ValueError:
                acceptance_state = None

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_order_detail.html",
        context={
            "title": order["order_no"] + "｜客服後台",
            "user": user,
            "order": order,
            "meta": meta,
            "customer_history": customer_history,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "workspace_assignments": workspace_assignments,
            "workspace_cs_payouts": workspace_cs_payouts,
            "acceptance_state": acceptance_state,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "cancellation_reason_labels": CANCELLATION_REASON_LABELS,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/order-workspace/{order_id}/edit")
async def admin_order_workspace_edit_r8(
    order_id: int,
    request: Request,
    customer_display_name: str = Form(default=""),
    customer_discord_id: str = Form(default=""),
    category: str = Form(default=""),
    item: str = Form(default=""),
    quantity: int = Form(default=1),
    amount: int = Form(default=0),
    payment_method: str = Form(default=""),
    status: str = Form(default="active"),
    cancellation_reason_code: str = Form(default=""),
    cancellation_reason_text: str = Form(default=""),
    closed_date: str = Form(default=""),
    closed_date_auto: str = Form(default=""),
    closed_date_touched: str = Form(default=""),
    customer_service_discord_id: str = Form(default=""),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    allowed_statuses = {
        "pending_cs_dispatch",
        "waiting_acceptance",
        "accepted_pending_pay",
        "created",
        "paid",
        "active",
        "stored",
        "completed",
        "done",
        "closed",
        "cancelled",
        "canceled",
    }

    customer_display_name = str(customer_display_name or "").strip()
    customer_discord_id = str(customer_discord_id or "").strip()
    category = str(category or "").strip()
    item = str(item or "").strip()
    payment_method = str(payment_method or "").strip()
    status = normalize_order_status(
        str(status or "active").strip().lower()
    )
    cancellation_reason_code = normalize_cancellation_reason_code(
        cancellation_reason_code
    )
    cancellation_reason_text = str(
        cancellation_reason_text or ""
    ).strip()
    closed_date = str(closed_date or "").strip()
    closed_date_auto = str(closed_date_auto or "").strip().lower()
    closed_date_touched = str(closed_date_touched or "").strip().lower()
    customer_service_discord_id = str(customer_service_discord_id or "").strip()

    if quantity < 1:
        return _mw4a2r6_redirect(order_id,request=request, error="數量至少要是 1。")

    if amount < 0:
        return _mw4a2r6_redirect(order_id,request=request, error="金額不能小於 0。")

    if status not in allowed_statuses:
        return _mw4a2r6_redirect(order_id,request=request, error="訂單狀態不在允許清單。")

    if closed_date and not _mw_r8_re.fullmatch(r"\d{4}-\d{2}-\d{2}", closed_date):
        return _mw4a2r6_redirect(order_id,request=request, error="結案日期格式必須是 YYYY-MM-DD。")

    loyalty_reconciled = False
    db = SessionLocal()

    try:
        before_row = db.execute(
            text("SELECT * FROM web_orders WHERE id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        if before_row is None:
            return _mw4a2r6_redirect(order_id,request=request, error="找不到這筆訂單。")

        before = _mw_r8_jsonable_row(before_row)
        previous_status = normalize_order_status(
            str(before.get("status") or "")
        )

        if status == CANCELLED:
            if (
                previous_status != CANCELLED
                and cancellation_reason_code == "unspecified"
            ):
                raise ValueError("取消訂單前請先選擇取消原因。")

            if previous_status != CANCELLED:
                transition_order_state_in_connection(
                    db.connection(),
                    order_id=int(order_id),
                    target_status=CANCELLED,
                    source="admin_order_workspace",
                    reason=(
                        cancellation_reason_text
                        or CANCELLATION_REASON_LABELS[
                            cancellation_reason_code
                        ]
                    ),
                    actor_discord_id=user.get("id"),
                    cancellation_reason_code=cancellation_reason_code,
                    cancellation_reason_text=cancellation_reason_text,
                )
            else:
                record_order_cancellation_in_connection(
                    db.connection(),
                    order_id=int(order_id),
                    reason_code=cancellation_reason_code,
                    reason_text=cancellation_reason_text,
                    source="admin_order_workspace",
                    actor_discord_id=user.get("id"),
                )

        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))

        previous_amount_for_finance = _mw4a2r6_safe_int(
            before.get("amount"),
            0,
        ) or 0
        previous_customer_pay_for_finance = _mw4a2r6_safe_int(
            before.get("customer_pay_amount"),
            None,
        )
        previous_payout_base_for_finance = _mw4a2r6_safe_int(
            before.get("payout_base_amount"),
            None,
        )

        preserved_financials = preserve_order_financial_gaps(
            previous_amount=int(previous_amount_for_finance),
            previous_customer_pay_amount=previous_customer_pay_for_finance,
            previous_payout_base_amount=previous_payout_base_for_finance,
            new_amount=int(amount),
        )
        new_customer_pay_amount = preserved_financials[
            "customer_pay_amount"
        ]
        new_payout_base_amount = int(
            preserved_financials["payout_base_amount"]
            or 0
        )

        if not customer_service_discord_id:
            customer_service_discord_id = str(
                before.get("customer_service_discord_id") or ""
            ).strip()

        customer_service_display_name = str(
            before.get("customer_service_display_name") or ""
        ).strip()

        if customer_service_discord_id:
            staff_member = get_staff_member_by_id(
                db,
                discord_id=customer_service_discord_id,
            )
            customer_service_display_name = (
                get_staff_display_name(staff_member)
                if staff_member is not None
                else customer_service_display_name
                or customer_service_discord_id
            )

        db.execute(
            text(
                """
                UPDATE web_orders
                SET
                    customer_display_name = :customer_display_name,
                    customer_discord_id = :customer_discord_id,
                    customer_service_discord_id = :customer_service_discord_id,
                    customer_service_display_name = :customer_service_display_name,
                    category = :category,
                    item = :item,
                    quantity = :quantity,
                    amount = :amount,
                    payout_base_amount = :payout_base_amount,
                    customer_pay_amount = :customer_pay_amount,
                    payment_method = :payment_method,
                    status = :status,
                    closed_at = CASE
                        WHEN COALESCE(closed_at, '') <> ''
                             AND :closed_date_touched NOT IN ('1', 'true', 'yes', 'on')
                             AND substr(closed_at, 1, 10) = :closed_date
                        THEN closed_at
                        WHEN :closed_date_auto IN ('1', 'true', 'yes', 'on')
                             AND :status IN ('closed', 'completed', 'done', 'cancelled', 'canceled')
                             AND COALESCE(closed_at, '') = ''
                        THEN datetime('now', '+8 hours')
                        WHEN :closed_date_touched IN ('1', 'true', 'yes', 'on')
                             AND :closed_date <> ''
                        THEN :closed_date
                        WHEN :status IN ('closed', 'completed', 'done', 'cancelled', 'canceled')
                             AND COALESCE(closed_at, '') = ''
                             AND :closed_date = ''
                        THEN datetime('now', '+8 hours')
                        ELSE closed_at
                    END,
                    updated_at = datetime('now')
                WHERE id = :order_id
                """
            ),
            {
                "customer_display_name": customer_display_name,
                "customer_discord_id": customer_discord_id,
                "customer_service_discord_id": customer_service_discord_id or None,
                "customer_service_display_name": customer_service_display_name or None,
                "category": category,
                "item": item,
                "quantity": int(quantity),
                "amount": int(amount),
                "payout_base_amount": int(new_payout_base_amount),
                "customer_pay_amount": (
                    int(new_customer_pay_amount)
                    if new_customer_pay_amount is not None
                    else None
                ),
                "payment_method": payment_method or None,
                "status": status,
                "closed_date": closed_date,
                "closed_date_auto": closed_date_auto,
                "closed_date_touched": closed_date_touched,
                "order_id": int(order_id),
            },
        )

        if _mw4a2r6_table_exists(db, "order_acceptance_meta"):
            meta_status_map = {
                "completed": "closed",
                "done": "closed",
                "canceled": "cancelled",
            }
            meta_status = meta_status_map.get(status, status)
            db.execute(
                text(
                    """
                    UPDATE order_acceptance_meta
                    SET status = :status,
                        updated_at = datetime('now')
                    WHERE order_id = :order_id
                    """
                ),
                {
                    "status": meta_status,
                    "order_id": int(order_id),
                },
            )

        db.flush()

        previous_amount = int(previous_amount_for_finance)
        previous_customer_pay_amount = previous_customer_pay_for_finance
        previous_effective_pay_amount = (
            int(previous_customer_pay_amount)
            if previous_customer_pay_amount is not None
            else int(previous_amount)
        )
        new_effective_pay_amount = (
            int(new_customer_pay_amount)
            if new_customer_pay_amount is not None
            else int(amount)
        )

        old_payment_method = str(
            before.get("payment_method")
            or ""
        ).strip()
        old_customer_discord_id = str(
            before.get("customer_discord_id")
            or ""
        ).strip()
        admin_display_name = str(
            user.get("global_name")
            or user.get("username")
            or user.get("name")
            or user.get("id")
            or ""
        ).strip()

        # Always enqueue a reconciliation. Besides Discord/VIP synchronization,
        # this event is the single idempotent bridge used to reconcile wallet
        # payment deltas after an admin changes a wallet-paid order.
        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_UPDATED,
            order_id=int(order_id),
            payload={
                "order_id": int(order_id),
                "source": "admin_order_workspace",
                "sync_kind": "order_amount_correction",
                "old_amount": int(previous_amount),
                "new_amount": int(amount),
                "old_customer_pay_amount": int(previous_effective_pay_amount),
                "new_customer_pay_amount": int(new_effective_pay_amount),
                "old_payment_method": old_payment_method,
                "new_payment_method": payment_method,
                "old_customer_discord_id": old_customer_discord_id,
                "new_customer_discord_id": customer_discord_id,
                "admin_discord_id": str(user.get("id") or ""),
                "admin_display_name": admin_display_name,
            },
        )

        active_assignment = db.execute(
            text(
                """
                SELECT 1
                FROM order_assignments
                WHERE order_id = :order_id
                  AND COALESCE(is_active, 1) = 1
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).fetchone()

        if active_assignment is not None and status in {
            "active",
            "stored",
            "completed",
            "done",
            "closed",
        }:
            if not customer_service_discord_id:
                raise ValueError(
                    "這張單已有正式接單人員，請先指定客服再儲存，避免分潤產生未指定客服。"
                )

            from web.app.services.order_service import recalculate_order_payouts

            recalculate_order_payouts(db, int(order_id))
            db.flush()
            _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)

        if previous_status == "closed" or status == "closed":
            from services.loyalty_benefits import (
                reconcile_loyalty_after_order_edit_in_connection,
            )

            reconcile_loyalty_after_order_edit_in_connection(
                db.connection(),
                order_id=int(order_id),
                previous_customer_id=old_customer_discord_id,
            )
            loyalty_reconciled = True

        after_row = db.execute(
            text("SELECT * FROM web_orders WHERE id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        from web.app.services.admin_service import write_admin_audit_log

        write_admin_audit_log(
            db,
            admin_user=user,
            action="order_workspace_edit",
            target_type="order",
            target_id=str(order_id),
            before=before,
            after=_mw_r8_jsonable_row(after_row),
        )

        db.commit()

    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))

    except Exception as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=f"訂單資料更新失敗：{exc}")

    finally:
        db.close()

    return _mw4a2r6_redirect(
        order_id,
        request=request,
        message=(
            "訂單資料已更新，福利進度已重新對帳。"
            if loyalty_reconciled
            else "訂單資料已更新。"
        ),
    )


@router.post("/admin/order-workspace/{order_id}/add-worker")
async def admin_order_workspace_add_worker_r8(
    order_id: int,
    request: Request,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        order_row = db.execute(
            text("SELECT status FROM web_orders WHERE id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        if order_row is None:
            raise ValueError("找不到這張訂單。")

        order_status = str(order_row.get("status") or "").strip().lower()
        staff_member = get_staff_member_by_id(db, discord_id=worker_discord_id)

        if staff_member is None or not bool(getattr(staff_member, "is_active", False)):
            raise ValueError("找不到這位有效的接單人員。")

        if not (
            bool(getattr(staff_member, "is_worker", False))
            or bool(getattr(staff_member, "is_companion", False))
        ):
            raise ValueError("這位人員目前沒有可接單的打手 / 陪玩身分。")

        worker_display_name = get_staff_display_name(staff_member)

        if order_status in PREPAY_ACCEPTANCE_STATUSES:
            try:
                staff_role_ids = json.loads(staff_member.roles_json or "[]")
            except Exception:
                staff_role_ids = []

            # claim_acceptance_order 使用獨立交易；先結束這個唯讀 Session 的 transaction，
            # 避免 SQLite 在同一時間持有讀鎖。
            db.rollback()

            state = claim_acceptance_order(
                order_id=int(order_id),
                staff_discord_id=str(worker_discord_id),
                staff_display_name=worker_display_name,
                staff_role_ids=staff_role_ids,
                source=f"admin_web:{user.get('id') or 'unknown'}",
            )

            create_sync_event(
                db,
                event_type=SyncEventType.ORDER_CLAIMED,
                order_id=int(order_id),
                payload={
                    "order_id": int(order_id),
                    "worker_discord_id": str(worker_discord_id),
                    "worker_display_name": worker_display_name,
                    "source": "admin_web",
                    "admin_discord_id": str(user.get("id") or ""),
                    "prepay_acceptance": True,
                    "accepted_count": state.accepted_count,
                    "required_staff_count": state.required_staff_count,
                    "status": state.status,
                },
            )
            db.commit()

            if state.is_full:
                return _mw4a2r6_redirect(
                    order_id,
                    request=request,
                    message=(
                        f"已補登接單人員（{state.accepted_count}/{state.required_staff_count}），"
                        "人數已滿，可進入付款程序。"
                    ),
                )

            return _mw4a2r6_redirect(
                order_id,
                request=request,
                message=f"已補登接單人員（{state.accepted_count}/{state.required_staff_count}）。",
            )

        if order_status in {"closed", "completed", "done", "cancelled", "canceled"}:
            raise ValueError("這張訂單已結案，不能再新增接單人員。")

        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        add_worker_to_order(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            admin_user=user,
            reason=reason,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()

    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="已新增接單人員，分潤已重新計算。")


@router.post("/admin/order-workspace/{order_id}/acceptance/{staff_discord_id}/remove")
async def admin_order_workspace_remove_acceptance_r8(
    order_id: int,
    staff_discord_id: str,
    request: Request,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        state = unclaim_acceptance_order(
            order_id=int(order_id),
            staff_discord_id=str(staff_discord_id),
            source=f"admin_web_remove:{user.get('id') or 'unknown'}",
        )

        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_UNCLAIMED,
            order_id=int(order_id),
            payload={
                "order_id": int(order_id),
                "worker_discord_id": str(staff_discord_id),
                "source": "admin_web",
                "admin_discord_id": str(user.get("id") or ""),
                "prepay_acceptance": True,
                "accepted_count": state.accepted_count,
                "required_staff_count": state.required_staff_count,
                "status": state.status,
            },
        )
        db.commit()

    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(
        order_id,
        request=request,
        message=f"已移除付款前接單人員（{state.accepted_count}/{state.required_staff_count}）。",
    )


@router.post("/admin/order-workspace/{order_id}/assignments/{assignment_id}/named-bonus")
async def admin_order_workspace_named_bonus_r8(
    order_id: int,
    assignment_id: int,
    request: Request,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        toggle_named_bonus_for_assignment(
            db,
            assignment_id=assignment_id,
            enabled=enabled == "on",
            admin_user=user,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="掛名加成已更新。")


@router.post("/admin/order-workspace/{order_id}/assignments/{assignment_id}/remove")
async def admin_order_workspace_remove_worker_r8(
    order_id: int,
    assignment_id: int,
    request: Request,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        remove_worker_from_order(
            db,
            assignment_id=assignment_id,
            admin_user=user,
            reason=reason,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="已移除接單人員，分潤已重新計算。")


@router.post("/admin/order-workspace/{order_id}/manual-payout")
async def admin_order_workspace_manual_payout_r8(
    order_id: int,
    request: Request,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        set_manual_worker_payout(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            manual_final_payout=manual_final_payout,
            reason=reason,
            admin_user=user,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="接單人員分潤金額已更新。")


@router.post("/admin/order-workspace/{order_id}/worker-payouts/{payout_id}/status")
async def admin_order_workspace_worker_payout_status_r8(
    order_id: int,
    payout_id: int,
    request: Request,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        set_worker_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="接單人員分潤狀態已更新。")


@router.post("/admin/order-workspace/{order_id}/customer-service-payouts/{payout_id}/status")
async def admin_order_workspace_cs_payout_status_r8(
    order_id: int,
    payout_id: int,
    request: Request,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        set_customer_service_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id,request=request, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id,request=request, message="客服分潤狀態已更新。")

# END MAWAN_R8_ORDER_WORKSPACE


@router.post(
    "/admin/order-workspace/{order_id}/internal-note"
)
async def admin_order_internal_note_r6(
    order_id: int,
    request: Request,
    internal_note: str = Form(
        default=""
    ),
):

    user = require_admin_user(
        request
    )


    if not user:

        return RedirectResponse(
            url="/service",
            status_code=303,
        )


    internal_note = str(
        internal_note
        or ""
    ).strip()


    if len(
        internal_note
    ) > 3000:

        return _mw4a2r6_redirect(
            order_id,
            request=request,
            error=
                "客服內部備註最多 3000 字。",
        )


    db = SessionLocal()


    try:

        exists = db.execute(
            text(
                """
                SELECT 1

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        ).fetchone()


        if exists is None:

            return _mw4a2r6_redirect(
                order_id,
                request=request,
                error=
                    "找不到這筆訂單。",
            )


        _mw4a2r6_ensure_meta_table(
            db
        )


        db.execute(
            text(
                """
                INSERT INTO
                web_admin_order_meta (

                    order_id,
                    internal_note,
                    updated_by_discord_id,
                    updated_by_display_name,
                    updated_at

                )

                VALUES (

                    :order_id,
                    :internal_note,
                    :updated_by_discord_id,
                    :updated_by_display_name,
                    CURRENT_TIMESTAMP

                )

                ON CONFLICT(order_id)
                DO UPDATE SET

                    internal_note =
                        excluded.internal_note,

                    updated_by_discord_id =
                        excluded.updated_by_discord_id,

                    updated_by_display_name =
                        excluded.updated_by_display_name,

                    updated_at =
                        CURRENT_TIMESTAMP
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),

                "internal_note":
                    internal_note,

                "updated_by_discord_id":
                    str(
                        user.get(
                            "id"
                        )
                        or ""
                    ),

                "updated_by_display_name":
                    _mw4a2r6_user_name(
                        user
                    ),
            },
        )


        db.commit()


    except Exception as exc:

        db.rollback()


        return _mw4a2r6_redirect(
            order_id,
            request=request,
            error=(
                "儲存客服內部備註失敗："
                + str(
                    exc
                )
            ),
        )


    finally:

        db.close()


    return _mw4a2r6_redirect(
        order_id,
        request=request,
        message=
            "客服內部備註已儲存。",
    )


@router.post(
    "/admin/order-workspace/{order_id}/attention"
)
async def admin_order_attention_r6(
    order_id: int,
    request: Request,
    enabled: str | None = Form(
        default=None
    ),
    attention_reason: str = Form(
        default=""
    ),
):

    user = require_admin_user(
        request
    )


    if not user:

        return RedirectResponse(
            url="/service",
            status_code=303,
        )


    enabled_value = (
        1

        if str(
            enabled
            or ""
        ).lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }

        else 0
    )


    attention_reason = str(
        attention_reason
        or ""
    ).strip()


    if len(
        attention_reason
    ) > 1000:

        return _mw4a2r6_redirect(
            order_id,
            request=request,
            error=
                "注意原因最多 1000 字。",
        )


    if not enabled_value:

        attention_reason = ""


    db = SessionLocal()


    try:

        exists = db.execute(
            text(
                """
                SELECT 1

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        ).fetchone()


        if exists is None:

            return _mw4a2r6_redirect(
                order_id,
                request=request,
                error=
                    "找不到這筆訂單。",
            )


        _mw4a2r6_ensure_meta_table(
            db
        )


        db.execute(
            text(
                """
                INSERT INTO
                web_admin_order_meta (

                    order_id,
                    needs_attention,
                    attention_reason,
                    updated_by_discord_id,
                    updated_by_display_name,
                    updated_at

                )

                VALUES (

                    :order_id,
                    :needs_attention,
                    :attention_reason,
                    :updated_by_discord_id,
                    :updated_by_display_name,
                    CURRENT_TIMESTAMP

                )

                ON CONFLICT(order_id)
                DO UPDATE SET

                    needs_attention =
                        excluded.needs_attention,

                    attention_reason =
                        excluded.attention_reason,

                    updated_by_discord_id =
                        excluded.updated_by_discord_id,

                    updated_by_display_name =
                        excluded.updated_by_display_name,

                    updated_at =
                        CURRENT_TIMESTAMP
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),

                "needs_attention":
                    enabled_value,

                "attention_reason":
                    attention_reason,

                "updated_by_discord_id":
                    str(
                        user.get(
                            "id"
                        )
                        or ""
                    ),

                "updated_by_display_name":
                    _mw4a2r6_user_name(
                        user
                    ),
            },
        )


        db.commit()


    except Exception as exc:

        db.rollback()


        return _mw4a2r6_redirect(
            order_id,
            request=request,
            error=(
                "更新注意標記失敗："
                + str(
                    exc
                )
            ),
        )


    finally:

        db.close()


    return _mw4a2r6_redirect(
        order_id,
        request=request,
        message=(
            "已標記為需注意。"

            if enabled_value

            else "已解除注意標記。"
        ),
    )
