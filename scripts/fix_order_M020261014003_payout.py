from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import (
    CustomerServicePayout,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import (
    calculate_customer_service_payout_base_amount,
    calculate_order_payout,
)


ORDER_NO = "M020261014003"
PAYOUT_BASE_AMOUNT = 2000


def main() -> None:
    db = SessionLocal()

    try:
        orders = list(
            db.scalars(
                select(WebOrder).where(WebOrder.bot_order_no == ORDER_NO)
            ).all()
        )
        if len(orders) != 1:
            raise RuntimeError(
                f"expected exactly one {ORDER_NO} order, found {len(orders)}"
            )

        order = orders[0]
        original_amount = order.amount
        original_customer_pay_amount = order.customer_pay_amount

        if int(order.amount or 0) != 0:
            raise RuntimeError(
                f"refusing repair: order amount is {order.amount}, expected 0"
            )
        if order.customer_pay_amount not in (None, 0):
            raise RuntimeError(
                "refusing repair: customer_pay_amount is not zero/null "
                f"({order.customer_pay_amount})"
            )

        worker_rows = list(
            db.scalars(
                select(WorkerPayout)
                .where(WorkerPayout.order_id == order.id)
                .order_by(WorkerPayout.id.asc())
            ).all()
        )
        if not worker_rows:
            raise RuntimeError("refusing repair: no existing worker payout rows")

        worker_ids = [str(row.worker_discord_id) for row in worker_rows]
        if len(worker_ids) != len(set(worker_ids)):
            raise RuntimeError("refusing repair: duplicate worker payout rows detected")

        named_bonus_worker_ids = [
            str(row.worker_discord_id)
            for row in worker_rows
            if bool(row.has_named_bonus)
        ]

        cs_rows = list(
            db.scalars(
                select(CustomerServicePayout)
                .where(CustomerServicePayout.order_id == order.id)
                .order_by(CustomerServicePayout.id.asc())
            ).all()
        )
        if len(cs_rows) != 1:
            raise RuntimeError(
                "refusing repair: expected exactly one customer-service payout row, "
                f"found {len(cs_rows)}"
            )

        overrides = {
            str(row.worker_discord_id): row
            for row in db.scalars(
                select(WorkerPayoutOverride).where(
                    WorkerPayoutOverride.order_id == order.id
                )
            ).all()
        }

        cs_base = calculate_customer_service_payout_base_amount(
            payout_base_amount=PAYOUT_BASE_AMOUNT,
            price_snapshot_json=order.price_snapshot_json,
        )
        result = calculate_order_payout(
            total_amount=PAYOUT_BASE_AMOUNT,
            worker_discord_ids=worker_ids,
            named_bonus_worker_ids=named_bonus_worker_ids,
            customer_service_total_amount=cs_base,
        )
        result_by_worker = {
            str(row.worker_discord_id): row for row in result.worker_payouts
        }

        if set(result_by_worker) != set(worker_ids):
            raise RuntimeError("refusing repair: payout engine worker set changed")

        print("=== BEFORE ===")
        print(f"order={ORDER_NO}")
        print(f"amount={order.amount}")
        print(f"customer_pay_amount={order.customer_pay_amount}")
        print(f"payout_base_amount={order.payout_base_amount}")
        for row in worker_rows:
            print(
                "worker "
                f"{row.worker_discord_id}: final={row.final_payout}, "
                f"status={row.payout_status}"
            )
        print(
            "customer_service "
            f"{cs_rows[0].customer_service_discord_id}: "
            f"amount={cs_rows[0].payout_amount}, status={cs_rows[0].payout_status}"
        )

        # Only this order's payout basis and payout amount fields are changed.
        # Customer-paid fields remain untouched so this promotional order still
        # contributes 0T to customer spending.
        order.payout_base_amount = PAYOUT_BASE_AMOUNT

        for row in worker_rows:
            calculated = result_by_worker[str(row.worker_discord_id)]
            row.gross_share = calculated.gross_share
            row.base_rate = calculated.base_rate
            row.base_payout = calculated.base_payout
            row.named_bonus_rate = calculated.named_bonus_rate
            row.named_bonus_amount = calculated.named_bonus_amount
            row.has_named_bonus = calculated.has_named_bonus

            override = overrides.get(str(row.worker_discord_id))
            row.final_payout = (
                int(override.manual_final_payout or 0)
                if override is not None
                else calculated.final_payout
            )
            # Intentionally preserve payout_status, paid_at, note and row id.

        cs_row = cs_rows[0]
        cs_row.rate = result.customer_service_rate
        cs_row.payout_amount = result.customer_service_payout
        # Intentionally preserve payout_status, paid_at, note and row id.

        db.flush()

        if order.amount != original_amount:
            raise RuntimeError("amount changed unexpectedly; rolling back")
        if order.customer_pay_amount != original_customer_pay_amount:
            raise RuntimeError(
                "customer_pay_amount changed unexpectedly; rolling back"
            )
        if int(order.payout_base_amount or 0) != PAYOUT_BASE_AMOUNT:
            raise RuntimeError("payout_base_amount did not update correctly")

        db.commit()

        print("=== AFTER ===")
        print(f"order={ORDER_NO}")
        print(f"amount={order.amount}")
        print(f"customer_pay_amount={order.customer_pay_amount}")
        print(f"payout_base_amount={order.payout_base_amount}")
        for row in worker_rows:
            print(
                "worker "
                f"{row.worker_discord_id}: final={row.final_payout}, "
                f"status={row.payout_status}"
            )
        print(
            "customer_service "
            f"{cs_row.customer_service_discord_id}: "
            f"amount={cs_row.payout_amount}, status={cs_row.payout_status}"
        )
        print("PASS: repaired only M020261014003 payout basis to 2000T")
        print("PASS: customer paid/spend basis remains 0T")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
