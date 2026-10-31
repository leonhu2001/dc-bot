from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, OrderAssignment, PayoutStatus, WebOrder, WorkerPayout
from shared.payout import (
    CUSTOMER_SERVICE_PAYOUT_RATE,
    LEGACY_CUSTOMER_SERVICE_GROSS_RATE,
    LEGACY_CUSTOMER_SERVICE_POLICY,
    WORKER_BASE_PAYOUT_RATE,
    calculate_customer_service_payout,
    calculate_customer_service_payout_base_amount,
)
from web.app.services.store_binding_payout import is_store_binding_effective_at
from web.app.services.store_binding_service import (
    STORE_BINDING_BONUS_RATE,
    STORE_BINDING_MAX_RATE,
)


TAIPEI_TZ = timezone(timedelta(hours=8))
WORKER_NAMED_BONUS_RATE = 0.03
WORKER_STREAM_BONUS_RATE = 0.02
WORKER_PREVIOUS_MONTH_SALARY_BONUS_RATE = 0.02
WORKER_PREVIOUS_MONTH_SALARY_THRESHOLD = 5000
LEGACY_WORKER_NAMED_BONUS_RATE = 0.05
MAX_NORMAL_WORKER_RATE = 0.87


def _finance_snapshot(order: WebOrder) -> dict:
    try:
        snapshot = json.loads(str(order.price_snapshot_json or "{}"))
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    finance = preview.get("finance") if isinstance(preview, dict) else None
    return finance if isinstance(finance, dict) else {}


def _is_legacy_order(order: WebOrder) -> bool:
    return str(_finance_snapshot(order).get("customer_service_payout_policy") or "") == LEGACY_CUSTOMER_SERVICE_POLICY


def _previous_month_utc_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    current = current.astimezone(TAIPEI_TZ)
    this_month = datetime(current.year, current.month, 1, tzinfo=TAIPEI_TZ)
    previous_day = this_month - timedelta(days=1)
    previous_month = datetime(previous_day.year, previous_day.month, 1, tzinfo=TAIPEI_TZ)
    return (
        previous_month.astimezone(timezone.utc).replace(tzinfo=None),
        this_month.astimezone(timezone.utc).replace(tzinfo=None),
    )


def previous_month_performance(db, worker_discord_id: str, *, now: datetime | None = None) -> int:
    """Return completed-order worker wages plus paid chicken-leg tips.

    Both parts are attributed by the order closing time. Payout status and
    payroll-transfer adjustments do not affect performance.
    """
    start_at, end_at = _previous_month_utc_bounds(now)
    order_date = func.coalesce(
        WebOrder.closed_at,
        WebOrder.updated_at,
        WebOrder.created_at,
    )
    wage_total = db.scalar(
        select(func.coalesce(func.sum(WorkerPayout.final_payout), 0))
        .join(WebOrder, WebOrder.id == WorkerPayout.order_id)
        .where(
            WorkerPayout.worker_discord_id == str(worker_discord_id),
            WebOrder.status == "closed",
            func.coalesce(WorkerPayout.final_payout, 0) > 0,
            order_date >= start_at,
            order_date < end_at,
        )
    )
    tip_total = db.scalar(
        text(
            """
            SELECT COALESCE(SUM(t.amount), 0)
            FROM worker_tips t
            JOIN web_orders w ON w.id = t.order_id
            WHERE CAST(t.worker_discord_id AS TEXT) = :worker_id
              AND w.status = 'closed'
              AND t.payment_status = 'paid'
              AND COALESCE(t.amount, 0) > 0
              AND COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) >= :start_at
              AND COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) < :end_at
            """
        ),
        {
            "worker_id": str(worker_discord_id),
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    return max(0, int(wage_total or 0) + int(tip_total or 0))


def previous_month_paid_salary(db, worker_discord_id: str, *, now: datetime | None = None) -> int:
    """Backward-compatible alias for callers that still use the old function name."""
    return previous_month_performance(db, worker_discord_id, now=now)


def _approved_stream_map(db, order_id: int) -> dict[str, bool]:
    rows = db.execute(
        text(
            """
            SELECT rw.worker_discord_id, rw.streamed
            FROM order_reports r
            JOIN order_report_workers rw ON rw.report_id = r.id
            WHERE r.order_id=:order_id AND r.status='approved'
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    return {
        str(row["worker_discord_id"]): bool(row["streamed"])
        for row in rows
        if str(row.get("worker_discord_id") or "").strip()
    }


def _assignment_stream_override_map(db, order_id: int) -> dict[str, bool]:
    rows = db.execute(
        select(
            OrderAssignment.worker_discord_id,
            OrderAssignment.stream_bonus_override,
        )
        .where(OrderAssignment.order_id == int(order_id))
        .where(OrderAssignment.is_active.is_(True))
        .where(OrderAssignment.stream_bonus_override.is_not(None))
        .order_by(OrderAssignment.id.asc())
    ).all()
    return {
        str(worker_id): bool(override)
        for worker_id, override in rows
        if str(worker_id or "").strip()
    }


def _effective_stream_bonus(
    *,
    legacy: bool,
    report_streamed: bool,
    override: bool | None,
) -> bool:
    if legacy:
        return False
    if override is None:
        return bool(report_streamed)
    return bool(override)


def _calculate_worker_rate(
    *,
    legacy: bool,
    named: bool,
    streamed: bool,
    previous_bonus: bool,
    store_bound: bool,
) -> float:
    """Calculate the worker rate without reading mutable current staff state."""
    if legacy:
        return WORKER_BASE_PAYOUT_RATE + (LEGACY_WORKER_NAMED_BONUS_RATE if named else 0.0)

    normal_rate = (
        WORKER_BASE_PAYOUT_RATE
        + (WORKER_NAMED_BONUS_RATE if named else 0.0)
        + (WORKER_STREAM_BONUS_RATE if streamed else 0.0)
        + (WORKER_PREVIOUS_MONTH_SALARY_BONUS_RATE if previous_bonus else 0.0)
    )
    normal_rate = min(MAX_NORMAL_WORKER_RATE, normal_rate)
    if not store_bound:
        return normal_rate
    return min(STORE_BINDING_MAX_RATE, normal_rate + STORE_BINDING_BONUS_RATE)


def apply_approved_report_worker_bonuses(order_id: int, *, now: datetime | None = None) -> dict:
    """Apply report-reviewed worker bonuses and then refresh CS margin share."""
    with SessionLocal() as db:
        order = db.get(WebOrder, int(order_id))
        if order is None:
            raise ValueError("找不到訂單。")

        legacy = _is_legacy_order(order)
        stream_map = _approved_stream_map(db, int(order_id))
        stream_override_map = _assignment_stream_override_map(db, int(order_id))
        payouts = list(
            db.scalars(
                select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
            ).all()
        )

        details: list[dict] = []
        for payout in payouts:
            worker_id = str(payout.worker_discord_id or "")
            previous_performance = previous_month_performance(db, worker_id, now=now)
            previous_bonus = (not legacy) and previous_performance >= WORKER_PREVIOUS_MONTH_SALARY_THRESHOLD
            stream_override = stream_override_map.get(worker_id)
            streamed = _effective_stream_bonus(
                legacy=legacy,
                report_streamed=bool(stream_map.get(worker_id)),
                override=stream_override,
            )
            named = bool(payout.has_named_bonus)
            store_bound = (not legacy) and is_store_binding_effective_at(
                db,
                worker_id,
                order.closed_at,
            )
            rate = _calculate_worker_rate(
                legacy=legacy,
                named=named,
                streamed=streamed,
                previous_bonus=previous_bonus,
                store_bound=store_bound,
            )

            gross = max(0, int(payout.gross_share or 0))
            base_payout = int(round(gross * WORKER_BASE_PAYOUT_RATE))
            named_amount = int(round(gross * (LEGACY_WORKER_NAMED_BONUS_RATE if legacy and named else WORKER_NAMED_BONUS_RATE if named else 0.0)))
            final_amount = int(round(gross * rate))

            manual_override = "手動指定分潤" in str(payout.note or "")
            locked = payout.payout_status == PayoutStatus.PAID.value or manual_override
            if not locked:
                payout.base_rate = WORKER_BASE_PAYOUT_RATE
                payout.base_payout = base_payout
                payout.named_bonus_rate = LEGACY_WORKER_NAMED_BONUS_RATE if legacy else WORKER_NAMED_BONUS_RATE
                payout.named_bonus_amount = named_amount
                payout.final_payout = final_amount
                payout.note = (
                    f"分潤：基礎80%"
                    + (f"＋掛名{5 if legacy else 3}%" if named else "")
                    + ("＋直播2%" if streamed else "")
                    + ("＋前月業績達5000T 2%" if previous_bonus else "")
                    + ("＋綁店3%" if store_bound else "")
                    + f"｜前月業績 {previous_performance}T"
                )

            details.append({
                "worker_id": worker_id,
                "rate": rate,
                "streamed": streamed,
                "stream_bonus_override": stream_override,
                "named": named,
                "previous_month_performance": previous_performance,
                "previous_month_paid_salary": previous_performance,
                "previous_month_bonus": previous_bonus,
                "store_bound_at_close": store_bound,
                "locked": locked,
            })

        db.flush()

        cs_row = db.scalar(
            select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
        )
        if cs_row is not None and cs_row.payout_status != PayoutStatus.PAID.value:
            payout_base = max(0, int(order.payout_base_amount if order.payout_base_amount is not None else order.amount or 0))
            cs_base = calculate_customer_service_payout_base_amount(
                payout_base_amount=payout_base,
                price_snapshot_json=order.price_snapshot_json,
            )
            if legacy:
                cs_rate = LEGACY_CUSTOMER_SERVICE_GROSS_RATE
                cs_amount = int(round(int(cs_base) * cs_rate))
            else:
                total_worker = sum(max(0, int(row.final_payout or 0)) for row in payouts)
                effective_worker_rate = min(1.0, total_worker / payout_base) if payout_base > 0 else WORKER_BASE_PAYOUT_RATE
                raw = calculate_customer_service_payout(
                    int(cs_base),
                    CUSTOMER_SERVICE_PAYOUT_RATE,
                    effective_worker_rate=effective_worker_rate,
                )
                cs_amount = int(round(raw))
                cs_rate = (cs_amount / int(cs_base)) if int(cs_base) > 0 else 0.0
            cs_row.rate = cs_rate
            cs_row.payout_amount = cs_amount

        db.commit()
        return {"order_id": int(order_id), "legacy": legacy, "workers": details}
