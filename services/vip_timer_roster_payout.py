from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import json

from sqlalchemy import select, text

from shared.db import SessionLocal
from shared.models import (
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import WORKER_BASE_PAYOUT_RATE, WORKER_NAMED_BONUS_RATE


_INSTALLED = False


def _is_timer_order(order_id: int, db) -> bool:
    row = db.execute(
        text("SELECT 1 FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1"),
        {"order_id": int(order_id)},
    ).first()
    return row is not None


def _staff_names(order_id: int, db) -> dict[str, str | None]:
    rows = db.execute(
        text(
            """
            SELECT staff_discord_id, staff_display_name
            FROM order_acceptance_claims
            WHERE order_id=:order_id
            ORDER BY id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    result: dict[str, str | None] = {}
    for row in rows:
        worker_id = str(row.get("staff_discord_id") or "").strip()
        if worker_id:
            result[worker_id] = str(row.get("staff_display_name") or "").strip() or result.get(worker_id)
    return result


def _raw_worker_shares(order_id: int, db) -> dict[str, Decimal]:
    rows = db.execute(
        text(
            """
            SELECT hourly_rate, billable_seconds, staff_ids_json
            FROM vip_timer_segments
            WHERE order_id=:order_id
              AND billable_seconds > 0
            ORDER BY seq ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    shares: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        try:
            staff = json.loads(str(row.get("staff_ids_json") or "[]"))
        except Exception:
            staff = []
        unique: list[str] = []
        for value in staff if isinstance(staff, list) else []:
            worker_id = str(value or "").strip()
            if worker_id and worker_id not in unique:
                unique.append(worker_id)
        if not unique:
            continue
        seconds = max(0, int(row.get("billable_seconds") or 0))
        rate = max(0, int(row.get("hourly_rate") or 0))
        segment_gross = Decimal(rate) * Decimal(seconds) / Decimal(3600)
        per_worker = segment_gross / Decimal(len(unique))
        for worker_id in unique:
            shares[worker_id] += per_worker
    return dict(shares)


def _allocate_integer_shares(raw: dict[str, Decimal], target_total: int) -> dict[str, int]:
    target = max(0, int(target_total or 0))
    if target <= 0 or not raw:
        return {worker_id: 0 for worker_id in raw}
    raw_total = sum(raw.values(), Decimal(0))
    if raw_total <= 0:
        return {worker_id: 0 for worker_id in raw}

    exact = {worker_id: Decimal(target) * amount / raw_total for worker_id, amount in raw.items()}
    allocated = {
        worker_id: int(value.to_integral_value(rounding=ROUND_FLOOR))
        for worker_id, value in exact.items()
    }
    remainder = target - sum(allocated.values())
    order = sorted(
        exact,
        key=lambda worker_id: (
            -(exact[worker_id] - Decimal(allocated[worker_id])),
            worker_id,
        ),
    )
    for worker_id in order[:remainder]:
        allocated[worker_id] += 1
    return allocated


def _rewrite_worker_payouts(db, order: WebOrder) -> int:
    payout_base = max(
        0,
        int(order.payout_base_amount if order.payout_base_amount is not None else order.amount or 0),
    )
    raw = _raw_worker_shares(int(order.id), db)
    shares = _allocate_integer_shares(raw, payout_base)
    if not shares:
        return 0

    names = _staff_names(int(order.id), db)
    overrides = {
        str(row.worker_discord_id): row
        for row in db.scalars(
            select(WorkerPayoutOverride).where(WorkerPayoutOverride.order_id == int(order.id))
        ).all()
    }

    existing_assignments = {
        str(row.worker_discord_id): row
        for row in db.scalars(
            select(OrderAssignment).where(OrderAssignment.order_id == int(order.id))
        ).all()
    }
    for worker_id in shares:
        if worker_id not in existing_assignments:
            db.add(
                OrderAssignment(
                    order_id=int(order.id),
                    worker_discord_id=worker_id,
                    worker_display_name=names.get(worker_id),
                    role_type="booster",
                    is_active=False,
                    has_named_bonus=False,
                    removed_at=datetime.now(),
                )
            )

    db.query(WorkerPayout).filter(WorkerPayout.order_id == int(order.id)).delete(synchronize_session=False)
    for worker_id in sorted(shares):
        gross_share = int(shares[worker_id])
        base_payout = int(gross_share * WORKER_BASE_PAYOUT_RATE)
        final_payout = base_payout
        note = "VIP 自由計時｜依各計時區段實際參與人員分帳"
        override = overrides.get(worker_id)
        if override is not None:
            final_payout = max(0, int(override.manual_final_payout or 0))
            reason = str(override.reason or "人工覆寫")
            note = f"{note}｜人工覆寫：{reason}"
        db.add(
            WorkerPayout(
                order_id=int(order.id),
                worker_discord_id=worker_id,
                worker_display_name=names.get(worker_id),
                gross_share=gross_share,
                base_rate=WORKER_BASE_PAYOUT_RATE,
                base_payout=base_payout,
                named_bonus_rate=WORKER_NAMED_BONUS_RATE,
                named_bonus_amount=0,
                has_named_bonus=False,
                final_payout=final_payout,
                payout_status=PayoutStatus.UNPAID.value,
                note=note,
            )
        )
    return len(shares)


def recalculate_vip_timer_worker_payouts(order_id: int) -> int:
    """Rebuild worker payouts from historical timer-segment participation.

    Segment gross is divided only among the staff recorded on that segment. The
    accumulated worker shares are then scaled to the canonical payout basis, so
    the 15-minute whole-order minimum and VIP percentage discount stay aligned
    with the existing financial policy without inventing a second billing rule.
    """
    db = SessionLocal()
    try:
        if not _is_timer_order(int(order_id), db):
            return 0
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return 0
        count = _rewrite_worker_payouts(db, order)
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def install_vip_timer_roster_payout() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from shared import order_acceptance as acceptance
    from web.app.services import order_service

    original_promote = acceptance.promote_acceptance_claims_to_assignments
    original_recalculate = order_service.recalculate_order_payouts

    def recalculate_with_timer_ledger(db, order):
        result = original_recalculate(db, order)
        if _is_timer_order(int(order.id), db):
            _rewrite_worker_payouts(db, order)
            db.flush()
        return result

    def promote_with_timer_ledger(*args, **kwargs):
        promoted = original_promote(*args, **kwargs)
        order_id = kwargs.get("order_id")
        if order_id is None and args:
            order_id = args[0]
        if order_id is not None:
            # Defensive second pass: callers that captured the pre-install
            # recalculate function still end with the segment-based ledger.
            recalculate_vip_timer_worker_payouts(int(order_id))
        return promoted

    order_service.recalculate_order_payouts = recalculate_with_timer_ledger
    acceptance.promote_acceptance_claims_to_assignments = promote_with_timer_ledger
    _INSTALLED = True


__all__ = [
    "install_vip_timer_roster_payout",
    "recalculate_vip_timer_worker_payouts",
]
