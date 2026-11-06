#!/usr/bin/env python3
"""One-time safe backfill for direct-pay orders mispriced after report approval.

Defaults to read-only preview. --apply touches ONLY closed unpaid special
orders, preserving every already-paid wage, customer-service payout and manual
override. Run only after the new payout policy has passed deploy.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import or_, select

from services.one_companion_one_guard_payout import (
    FULL_WORKER_PAYOUT_RULE_KEYS,
    is_full_worker_payout_rule,
)
from services.staff_internal_ammo_dump_policy import calculate_internal_ammo_dump_cs_payout
from shared.db import SessionLocal
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)


def repair_unpaid_full_worker_payouts(*, apply: bool = False) -> dict:
    counts: Counter[str] = Counter()
    changes: list[dict] = []
    with SessionLocal() as db:
        orders = list(
            db.scalars(
                select(WebOrder)
                .where(WebOrder.status == "closed")
                .where(
                    or_(
                        WebOrder.order_rule_key.in_(tuple(FULL_WORKER_PAYOUT_RULE_KEYS)),
                        WebOrder.order_rule_key.like("farm_aw_collision_%"),
                    )
                )
                .order_by(WebOrder.id)
            ).all()
        )
        for order in orders:
            if not is_full_worker_payout_rule(order.order_rule_key):
                continue

            payouts = list(db.scalars(
                select(WorkerPayout).where(WorkerPayout.order_id == order.id)
                .order_by(WorkerPayout.id)
            ).all())
            cs_rows = list(db.scalars(
                select(CustomerServicePayout).where(CustomerServicePayout.order_id == order.id)
            ).all())
            if not payouts:
                counts["skip_no_worker_payout"] += 1
                continue

            # Do not alter any settled accounting history even when one side
            # (worker or CS) has been paid and the other side is still unpaid.
            all_rows = [*payouts, *cs_rows]
            if any(
                row.payout_status != PayoutStatus.UNPAID.value
                or row.paid_at is not None
                for row in all_rows
            ):
                counts["skip_paid_or_locked"] += 1
                continue

            manual_overrides = db.scalar(
                select(WorkerPayoutOverride.id)
                .where(WorkerPayoutOverride.order_id == order.id).limit(1)
            )
            if manual_overrides is not None or any(
                "手動指定分潤" in str(row.note or "") for row in payouts
            ):
                counts["skip_manual_override"] += 1
                continue

            active_ids = {
                str(worker_id) for worker_id in db.scalars(
                    select(OrderAssignment.worker_discord_id)
                    .where(OrderAssignment.order_id == order.id)
                    .where(OrderAssignment.is_active.is_(True))
                ).all()
            }
            payout_ids = [str(row.worker_discord_id) for row in payouts]
            if not active_ids or set(payout_ids) != active_ids or len(payout_ids) != len(active_ids):
                counts["skip_roster_mismatch"] += 1
                continue

            expected_basis = max(0, int(
                order.payout_base_amount
                if order.payout_base_amount is not None
                else order.amount or 0
            ))
            # Do not "repair" an already corrupted pricing basis by giving
            # the worker 3,000T on an unnamed 500M order. Named and unnamed
            # always use the same 2,650T worker basis; the extra 350T stays
            # split between CS and the store. Other internal prices are fixed per product.
            internal_basis = {
                "staff_internal_ammo_dump_500m": 2650,
                "staff_internal_car_500m": 2480,
            }.get(str(order.order_rule_key or ""))
            if internal_basis is not None and expected_basis != internal_basis:
                counts["skip_invalid_internal_basis"] += 1
                continue
            if str(order.order_rule_key or "") == "staff_internal_aw_collision" and expected_basis % 4:
                counts["skip_invalid_internal_basis"] += 1
                continue

            if expected_basis <= 0 or sum(max(0, int(row.gross_share or 0)) for row in payouts) != expected_basis:
                counts["skip_gross_mismatch"] += 1
                continue

            customer_pay = max(0, int(
                order.customer_pay_amount
                if order.customer_pay_amount is not None
                else order.amount or 0
            ))
            expected_cs = calculate_internal_ammo_dump_cs_payout(
                order.order_rule_key, customer_pay, expected_basis
            )
            # A positive CS share requires exactly one real customer-service
            # payout row; don't claim a successful fix without one.
            if expected_cs > 0 and len(cs_rows) != 1:
                counts["skip_missing_cs_payout"] += 1
                continue

            old_worker_total = sum(int(row.final_payout or 0) for row in payouts)
            old_cs_total = sum(int(row.payout_amount or 0) for row in cs_rows)
            already_correct = (
                old_worker_total == expected_basis
                and old_cs_total == expected_cs
                and all(
                    abs(float(row.base_rate or 0) - 1.0) < 0.00001
                    and int(row.named_bonus_amount or 0) == 0
                    for row in payouts
                )
                and all(
                    abs(float(row.rate or 0) - (
                        expected_cs / customer_pay if customer_pay else 0
                    )) < 0.00001
                    for row in cs_rows
                )
            )
            if already_correct:
                counts["already_correct"] += 1
                continue

            changes.append({
                "order_id": order.id,
                "order_rule_key": order.order_rule_key,
                "customer_pay": customer_pay,
                "worker_before": old_worker_total,
                "worker_after": expected_basis,
                "cs_before": old_cs_total,
                "cs_after": expected_cs,
                "store_after": customer_pay - expected_basis - expected_cs,
            })
            counts["correctable"] += 1
            if not apply:
                continue

            for row in payouts:
                gross = max(0, int(row.gross_share or 0))
                row.base_rate = 1.0
                row.base_payout = gross
                row.named_bonus_rate = 0.0
                row.named_bonus_amount = 0
                row.final_payout = gross
                row.note = "特殊代肝單｜接單人員全額 100%｜無客服分潤及額外獎金"
            for row in cs_rows:
                row.rate = expected_cs / customer_pay if customer_pay else 0.0
                row.payout_amount = expected_cs
            counts["fixed"] += 1

        if apply:
            db.commit()
        else:
            db.rollback()

    return {
        "mode": "applied" if apply else "dry-run",
        "counts": dict(counts),
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply changes to safe unpaid orders")
    arguments = parser.parse_args()
    result = repair_unpaid_full_worker_payouts(apply=arguments.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
