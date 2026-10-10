from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from shared.db import SessionLocal, engine
from shared.models import (
    AdminAuditLog,
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from web.app.services.checkout_preview import calculate_point_service_value
from web.app.services.order_service import (
    _customer_service_payout_base,
    recalculate_order_payouts,
)


REPAIR_TABLE = "one_time_data_repairs"
MO20261007003_REPAIR_KEY = "2026-10-10:MO20261007003:point-extra-hour-payout-v1"
MO20261007003_CS_REPAIR_KEY = "2026-10-10:MO20261007003:exclude-gifted-hour-from-cs-v1"


def ensure_data_repair_table(bind=engine) -> None:
    with bind.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {REPAIR_TABLE} (
                    repair_key TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    note TEXT
                )
                """
            )
        )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def _order_price_context(order: WebOrder) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = _json_dict(order.price_snapshot_json)
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    preview = dict(preview or {})
    quote = preview.get("quote") if isinstance(preview.get("quote"), dict) else {}
    finance = preview.get("finance") if isinstance(preview.get("finance"), dict) else {}
    return snapshot, dict(quote or {}), dict(finance or {})


def _historical_quote_for_point_hour(order: WebOrder) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot, quote, finance = _order_price_context(order)

    quantity = max(1, _to_int(quote.get("quantity"), int(order.quantity or 1)))
    service_amount = _to_int(quote.get("customer_pay_amount"), 0)

    if service_amount <= 0:
        service_amount = _to_int(finance.get("service_amount"), 0)

    if service_amount <= 0:
        rule_snapshot = _json_dict(order.rule_snapshot_json)
        unit_price = max(0, _to_int(rule_snapshot.get("price"), 0))
        player_count = max(1, _to_int(quote.get("player_count"), 1))
        if bool(rule_snapshot.get("price_multiply_player_count")):
            unit_price *= player_count
        service_amount = unit_price * quantity

    if service_amount <= 0:
        # Historical WebOrder.original_amount is the service list amount for the
        # modern checkout path. Keep this as the last fallback only.
        service_amount = max(0, int(order.original_amount or 0))

    return snapshot, {
        **quote,
        "quantity": quantity,
        "customer_pay_amount": service_amount,
    }, finance


def _point_hour_evidence(db: Session, order: WebOrder, snapshot: dict[str, Any]) -> dict[str, Any]:
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    preview = dict(preview or {})
    point = preview.get("point") if isinstance(preview.get("point"), dict) else {}
    finance = preview.get("finance") if isinstance(preview.get("finance"), dict) else {}

    keys: set[str] = set()
    snapshot_key = str((point or {}).get("key") or "").strip()
    if snapshot_key:
        keys.add(snapshot_key)

    inspector = sa_inspect(db.get_bind())
    if "web_checkout_point_transactions" in set(inspector.get_table_names()):
        rows = db.execute(
            text(
                """
                SELECT point_item_key
                FROM web_checkout_point_transactions
                WHERE order_id = :order_id
                ORDER BY id ASC
                """
            ),
            {"order_id": int(order.id)},
        ).fetchall()
        for row in rows:
            key = str(row[0] or "").strip()
            if key:
                keys.add(key)

    note = str((finance or {}).get("point_service_note") or "").strip()
    one_hour = bool(
        keys & {"extra_30", "extra_hour_1h", "free_play_1h"}
        or ("1 小時" in note and "服務時間" in note)
        or ("一小時" in note and "服務時間" in note)
    )

    return {
        "keys": sorted(keys),
        "finance_note": note,
        "one_hour": one_hour,
    }


def _payout_rows_are_safe(db: Session, order_id: int) -> tuple[bool, str]:
    worker_rows = list(
        db.scalars(
            select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
        ).all()
    )
    cs_rows = list(
        db.scalars(
            select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
        ).all()
    )

    for row in [*worker_rows, *cs_rows]:
        status = str(getattr(row, "payout_status", "") or "").strip().lower()
        if status == PayoutStatus.PAID.value or getattr(row, "paid_at", None) is not None:
            return False, "existing payout has already been paid"

    override = db.scalar(
        select(WorkerPayoutOverride)
        .where(WorkerPayoutOverride.order_id == int(order_id))
        .limit(1)
    )
    if override is not None:
        return False, "worker payout override exists"

    assignment_count = len(
        list(
            db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == int(order_id))
                .where(OrderAssignment.is_active.is_(True))
            ).all()
        )
    )
    if assignment_count <= 0:
        return False, "no active worker assignment"

    return True, ""


def _repair_already_applied(db: Session, repair_key: str) -> bool:
    row = db.execute(
        text(
            f"SELECT repair_key FROM {REPAIR_TABLE} WHERE repair_key = :repair_key LIMIT 1"
        ),
        {"repair_key": str(repair_key)},
    ).first()
    return row is not None


def repair_mo20261007003_point_hour_payout(db: Session) -> dict[str, Any]:
    """Top up MO20261007003 to the current store-funded +1h point payout rule.

    This is a one-time data correction, not a permanent business-rule override.
    It never changes the customer's historical point deduction or amount paid.
    """
    repair_key = MO20261007003_REPAIR_KEY
    if _repair_already_applied(db, repair_key):
        return {"status": "already_applied", "repair_key": repair_key}

    order = db.scalar(
        select(WebOrder)
        .where(WebOrder.bot_order_no == "MO20261007003")
        .limit(1)
    )
    if order is None:
        return {"status": "not_found", "repair_key": repair_key}

    if str(order.status or "").strip().lower() == "cancelled":
        return {"status": "skipped", "repair_key": repair_key, "reason": "order is cancelled"}

    safe, reason = _payout_rows_are_safe(db, int(order.id))
    if not safe:
        return {"status": "skipped", "repair_key": repair_key, "reason": reason, "order_id": int(order.id)}

    snapshot, quote, finance = _historical_quote_for_point_hour(order)
    evidence = _point_hour_evidence(db, order, snapshot)

    # The shop owner explicitly identified this order as the historical +1 hour
    # point-benefit order. Evidence is still recorded for audit/debugging, but the
    # exact order number is the authorization boundary for this one-time repair.
    expected_point_value = calculate_point_service_value(
        quote=quote,
        vip_pay_rate=100,
        point_item={"kind": "extra_hours", "hours": 1},
    )
    if expected_point_value <= 0:
        return {
            "status": "skipped",
            "repair_key": repair_key,
            "reason": "could not derive one-hour list value",
            "order_id": int(order.id),
            "evidence": evidence,
        }

    current_payout_base = max(0, int(order.payout_base_amount or order.amount or 0))
    old_point_value = max(0, _to_int(finance.get("point_service_value"), 0))
    snapshot_payout_base = max(0, _to_int(finance.get("payout_base_amount"), 0))

    if snapshot_payout_base > 0:
        base_without_old_point = max(0, snapshot_payout_base - old_point_value)
        target_payout_base = max(current_payout_base, base_without_old_point + expected_point_value)
    else:
        target_payout_base = current_payout_base + max(0, expected_point_value - old_point_value)

    delta = max(0, target_payout_base - current_payout_base)
    if delta <= 0:
        # The order already has at least the current +1h list-value payout base.
        db.execute(
            text(
                f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) VALUES (:repair_key, :applied_at, :note)"
            ),
            {
                "repair_key": repair_key,
                "applied_at": datetime.utcnow().isoformat(timespec="seconds"),
                "note": "No delta required; payout base already includes current one-hour point value.",
            },
        )
        return {
            "status": "already_correct",
            "repair_key": repair_key,
            "order_id": int(order.id),
            "expected_point_value": expected_point_value,
            "payout_base_amount": current_payout_base,
            "evidence": evidence,
        }

    before_worker = {
        str(row.worker_discord_id): int(round(float(row.final_payout or 0)))
        for row in db.scalars(
            select(WorkerPayout).where(WorkerPayout.order_id == int(order.id))
        ).all()
    }
    before = {
        "payout_base_amount": current_payout_base,
        "store_absorbed_amount": int(order.store_absorbed_amount or 0),
        "point_service_value": old_point_value,
        "worker_payouts": before_worker,
    }

    order.payout_base_amount = target_payout_base
    order.store_absorbed_amount = int(order.store_absorbed_amount or 0) + delta

    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    if isinstance(preview, dict):
        finance_target = preview.setdefault("finance", {})
        if isinstance(finance_target, dict):
            finance_target["point_service_note"] = "服務時間 +1 小時"
            finance_target["point_service_value"] = expected_point_value
            finance_target["payout_base_amount"] = target_payout_base
            finance_target["payout_base_preview"] = target_payout_base
            finance_target["point_store_absorbed_amount"] = max(
                expected_point_value,
                _to_int(finance_target.get("point_store_absorbed_amount"), 0) + delta,
            )
            finance_target["store_absorbed_amount"] = int(order.store_absorbed_amount or 0)
            finance_target["store_absorbed_preview"] = int(order.store_absorbed_amount or 0)

    order.price_snapshot_json = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    db.flush()

    recalculate_order_payouts(db, int(order.id))
    db.flush()

    after_worker = {
        str(row.worker_discord_id): int(round(float(row.final_payout or 0)))
        for row in db.scalars(
            select(WorkerPayout).where(WorkerPayout.order_id == int(order.id))
        ).all()
    }
    after = {
        "payout_base_amount": int(order.payout_base_amount or 0),
        "store_absorbed_amount": int(order.store_absorbed_amount or 0),
        "point_service_value": expected_point_value,
        "worker_payouts": after_worker,
    }

    db.add(
        AdminAuditLog(
            admin_discord_id="system",
            action="data_repair_point_extra_hour_payout",
            target_type="order",
            target_id=str(int(order.id)),
            before_json=json.dumps(
                {"order_no": "MO20261007003", "evidence": evidence, **before},
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {
                    "order_no": "MO20261007003",
                    "expected_point_service_value": expected_point_value,
                    "delta": delta,
                    **after,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.utcnow(),
        )
    )
    db.execute(
        text(
            f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) VALUES (:repair_key, :applied_at, :note)"
        ),
        {
            "repair_key": repair_key,
            "applied_at": datetime.utcnow().isoformat(timespec="seconds"),
            "note": f"MO20261007003 current +1h point payout applied; payout-base delta={delta}T.",
        },
    )

    return {
        "status": "applied",
        "repair_key": repair_key,
        "order_id": int(order.id),
        "expected_point_value": expected_point_value,
        "delta": delta,
        "before": before,
        "after": after,
        "evidence": evidence,
    }



def repair_mo20261007003_customer_service_payout(db: Session) -> dict[str, Any]:
    """Remove the point-gifted hour from CS commission without touching workers."""
    repair_key = MO20261007003_CS_REPAIR_KEY
    if _repair_already_applied(db, repair_key):
        return {"status": "already_applied", "repair_key": repair_key}

    order = db.scalar(
        select(WebOrder)
        .where(WebOrder.bot_order_no == "MO20261007003")
        .limit(1)
    )
    if order is None:
        return {"status": "not_found", "repair_key": repair_key}

    rows = list(
        db.scalars(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == int(order.id))
            .order_by(CustomerServicePayout.id.asc())
        ).all()
    )
    if not rows:
        return {
            "status": "skipped",
            "repair_key": repair_key,
            "order_id": int(order.id),
            "reason": "no customer-service payout row",
        }

    for row in rows:
        if str(row.payout_status or "").strip().lower() == PayoutStatus.PAID.value or row.paid_at is not None:
            return {
                "status": "skipped",
                "repair_key": repair_key,
                "order_id": int(order.id),
                "reason": "customer-service payout already paid",
            }

    cs_base = _customer_service_payout_base(order)
    before = [
        {
            "id": int(row.id),
            "rate": float(row.rate or 0),
            "payout_amount": float(row.payout_amount or 0),
        }
        for row in rows
    ]

    for row in rows:
        row.payout_amount = cs_base * float(row.rate or 0)

    db.flush()
    after = [
        {
            "id": int(row.id),
            "rate": float(row.rate or 0),
            "payout_amount": float(row.payout_amount or 0),
        }
        for row in rows
    ]

    db.add(
        AdminAuditLog(
            admin_discord_id="system",
            action="data_repair_exclude_gifted_service_from_cs_payout",
            target_type="order",
            target_id=str(int(order.id)),
            before_json=json.dumps(
                {"order_no": "MO20261007003", "customer_service_payouts": before},
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {
                    "order_no": "MO20261007003",
                    "customer_service_payout_base": cs_base,
                    "customer_service_payouts": after,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.utcnow(),
        )
    )
    db.execute(
        text(
            f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) "
            "VALUES (:repair_key, :applied_at, :note)"
        ),
        {
            "repair_key": repair_key,
            "applied_at": datetime.utcnow().isoformat(timespec="seconds"),
            "note": (
                "MO20261007003 CS commission reset to paid-service base; "
                f"cs_base={cs_base}T."
            ),
        },
    )

    return {
        "status": "applied",
        "repair_key": repair_key,
        "order_id": int(order.id),
        "customer_service_payout_base": cs_base,
        "before": before,
        "after": after,
    }


def apply_known_data_repairs() -> list[dict[str, Any]]:
    ensure_data_repair_table()
    db = SessionLocal()
    try:
        point_result = repair_mo20261007003_point_hour_payout(db)
        cs_result = repair_mo20261007003_customer_service_payout(db)
        db.commit()
        return [point_result, cs_result]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
