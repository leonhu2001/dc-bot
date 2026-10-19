from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from web.app.services.admin_order_workspace_data import (
    _mw4a2r6_safe_int,
    _mw4a2r6_table_exists,
)
from web.app.services.order_financial_edit import preserve_order_financial_gaps
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
)


@dataclass(frozen=True)
class OrderWorkspaceFieldWriteResult:
    customer_service_discord_id: str
    previous_amount: int
    previous_customer_pay_amount: int | None
    new_customer_pay_amount: int | None


def write_order_workspace_fields(
    db,
    *,
    order_id: int,
    before: dict,
    customer_display_name: str,
    customer_discord_id: str,
    category: str,
    item: str,
    quantity: int,
    amount: int,
    payment_method: str,
    status: str,
    closed_date: str,
    closed_date_auto: str,
    closed_date_touched: str,
    customer_service_discord_id: str,
) -> OrderWorkspaceFieldWriteResult:
    previous_amount = _mw4a2r6_safe_int(before.get("amount"), 0) or 0
    previous_customer_pay_amount = _mw4a2r6_safe_int(
        before.get("customer_pay_amount"), None
    )
    previous_payout_base_amount = _mw4a2r6_safe_int(
        before.get("payout_base_amount"), None
    )
    preserved_financials = preserve_order_financial_gaps(
        previous_amount=int(previous_amount),
        previous_customer_pay_amount=previous_customer_pay_amount,
        previous_payout_base_amount=previous_payout_base_amount,
        new_amount=int(amount),
    )
    new_customer_pay_amount = preserved_financials["customer_pay_amount"]
    new_payout_base_amount = int(preserved_financials["payout_base_amount"] or 0)

    resolved_customer_service_id = str(customer_service_discord_id or "").strip()
    if not resolved_customer_service_id:
        resolved_customer_service_id = str(
            before.get("customer_service_discord_id") or ""
        ).strip()

    customer_service_display_name = str(
        before.get("customer_service_display_name") or ""
    ).strip()
    if resolved_customer_service_id:
        staff_member = get_staff_member_by_id(
            db,
            discord_id=resolved_customer_service_id,
        )
        customer_service_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else customer_service_display_name or resolved_customer_service_id
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
            "customer_service_discord_id": resolved_customer_service_id or None,
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
            {"status": meta_status, "order_id": int(order_id)},
        )

    db.flush()

    return OrderWorkspaceFieldWriteResult(
        customer_service_discord_id=resolved_customer_service_id,
        previous_amount=int(previous_amount),
        previous_customer_pay_amount=(
            int(previous_customer_pay_amount)
            if previous_customer_pay_amount is not None
            else None
        ),
        new_customer_pay_amount=(
            int(new_customer_pay_amount)
            if new_customer_pay_amount is not None
            else None
        ),
    )
