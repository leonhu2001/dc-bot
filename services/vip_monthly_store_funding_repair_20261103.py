from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from core.time_utils import utc_now_naive
from shared.db import SessionLocal, engine
from shared.models import AdminAuditLog, WebOrder, WorkerPayout
from services.data_repairs import (
    REPAIR_TABLE,
    _payout_rows_are_safe,
    _repair_already_applied,
    ensure_data_repair_table,
)
from web.app.services.order_service import recalculate_order_payouts


REPAIR_VERSION = "2026-11-03-v1"
MONTH_START = datetime(2026, 11, 1)
MONTH_END = datetime(2026, 12, 1)
VIP_MONTHLY_KEYS = {"monthly_coupon_200", "monthly_coupon_500"}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _to_int(value: Any) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _preview_and_finance(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    preview = snapshot.get("preview")
    if not isinstance(preview, dict):
        preview = snapshot
    finance = preview.get("finance") if isinstance(preview, dict) else None
    if not isinstance(finance, dict):
        finance = {}
        if isinstance(preview, dict):
            preview["finance"] = finance
    return preview, finance


def _monthly_evidence(snapshot: dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
    preview, finance = _preview_and_finance(snapshot)
    candidates = [finance]
    if isinstance(preview, dict):
        candidates.append(preview)
    candidates.append(snapshot)

    benefit_key = ""
    amount = 0
    source: dict[str, Any] = finance
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = str(candidate.get("vip_monthly_benefit_key") or "").strip()
        cash = _to_int(candidate.get("vip_monthly_cash_amount"))
        if key in VIP_MONTHLY_KEYS and cash > 0:
            benefit_key = key
            amount = cash
            source = candidate
            break

    return benefit_key, amount, source


def _repair_key(order_id: int) -> str:
    return f"{REPAIR_VERSION}:vip-monthly-store-funded:order-{int(order_id)}"


def repair_november_vip_monthly_store_funding() -> dict[str, Any]:
    """Repair November orders created while VIP monthly cash was shared-funded.

    Only orders with explicit monthly-voucher evidence in their price snapshot are
    touched. Customer payment never changes. The monthly cash amount is restored
    to the payroll basis and recorded as store absorbed. Unpaid payout rows are
    recalculated; already-paid/overridden rows are preserved so payment history is
    never falsified.
    """
    ensure_data_repair_table(engine)
    db = SessionLocal()
    summary: dict[str, Any] = {
        "matched": 0,
        "repaired": 0,
        "payouts_recalculated": 0,
        "payouts_preserved": 0,
        "already_applied": 0,
        "orders": [],
    }

    try:
        orders = list(
            db.scalars(
                select(WebOrder)
                .where(WebOrder.created_at >= MONTH_START)
                .where(WebOrder.created_at < MONTH_END)
                .where(WebOrder.status.notin_(["cancelled", "canceled"]))
                .order_by(WebOrder.id.asc())
            ).all()
        )

        for order in orders:
            snapshot = _as_dict(order.price_snapshot_json)
            benefit_key, monthly_amount, evidence_source = _monthly_evidence(snapshot)
            if benefit_key not in VIP_MONTHLY_KEYS or monthly_amount <= 0:
                continue

            summary["matched"] += 1
            repair_key = _repair_key(int(order.id))
            if _repair_already_applied(db, repair_key):
                summary["already_applied"] += 1
                continue

            if str(evidence_source.get("vip_monthly_funding") or "").strip() == "store":
                db.execute(
                    text(
                        f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) "
                        "VALUES (:repair_key, :applied_at, :note)"
                    ),
                    {
                        "repair_key": repair_key,
                        "applied_at": utc_now_naive().isoformat(timespec="seconds"),
                        "note": "Already store-funded in source snapshot; no accounting delta required.",
                    },
                )
                summary["already_applied"] += 1
                continue

            old_payout_base = _to_int(order.payout_base_amount or order.amount)
            old_store_absorbed = _to_int(order.store_absorbed_amount)
            new_payout_base = old_payout_base + monthly_amount
            new_store_absorbed = old_store_absorbed + monthly_amount

            before_worker = {
                str(row.worker_discord_id): _to_int(row.final_payout)
                for row in db.scalars(
                    select(WorkerPayout).where(WorkerPayout.order_id == int(order.id))
                ).all()
            }

            order.payout_base_amount = new_payout_base
            order.store_absorbed_amount = new_store_absorbed

            preview, finance = _preview_and_finance(snapshot)
            finance["vip_monthly_benefit_key"] = benefit_key
            finance["vip_monthly_cash_amount"] = monthly_amount
            finance["vip_monthly_funding"] = "store"
            finance["vip_monthly_store_funding_repair"] = REPAIR_VERSION
            finance["payout_base_amount"] = new_payout_base
            finance["payout_base_preview"] = new_payout_base
            finance["store_absorbed_amount"] = new_store_absorbed
            finance["store_absorbed_preview"] = new_store_absorbed
            evidence_source["vip_monthly_funding"] = "store"
            evidence_source["vip_monthly_store_funding_repair"] = REPAIR_VERSION

            order.price_snapshot_json = json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            db.flush()

            payout_safe, payout_reason = _payout_rows_are_safe(db, int(order.id))
            if payout_safe:
                recalculate_order_payouts(db, int(order.id))
                db.flush()
                summary["payouts_recalculated"] += 1
                payout_action = "recalculated"
            else:
                summary["payouts_preserved"] += 1
                payout_action = f"preserved: {payout_reason}"

            after_worker = {
                str(row.worker_discord_id): _to_int(row.final_payout)
                for row in db.scalars(
                    select(WorkerPayout).where(WorkerPayout.order_id == int(order.id))
                ).all()
            }

            db.add(
                AdminAuditLog(
                    admin_discord_id="system",
                    action="data_repair_vip_monthly_store_funding",
                    target_type="order",
                    target_id=str(int(order.id)),
                    before_json=json.dumps(
                        {
                            "order_no": order.bot_order_no,
                            "vip_monthly_benefit_key": benefit_key,
                            "vip_monthly_cash_amount": monthly_amount,
                            "payout_base_amount": old_payout_base,
                            "store_absorbed_amount": old_store_absorbed,
                            "worker_payouts": before_worker,
                        },
                        ensure_ascii=False,
                    ),
                    after_json=json.dumps(
                        {
                            "order_no": order.bot_order_no,
                            "vip_monthly_benefit_key": benefit_key,
                            "vip_monthly_cash_amount": monthly_amount,
                            "payout_base_amount": new_payout_base,
                            "store_absorbed_amount": new_store_absorbed,
                            "customer_pay_amount": _to_int(order.customer_pay_amount or order.amount),
                            "payout_action": payout_action,
                            "worker_payouts": after_worker,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=utc_now_naive(),
                )
            )
            db.execute(
                text(
                    f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) "
                    "VALUES (:repair_key, :applied_at, :note)"
                ),
                {
                    "repair_key": repair_key,
                    "applied_at": utc_now_naive().isoformat(timespec="seconds"),
                    "note": (
                        f"VIP monthly {monthly_amount}T moved from shared funding to store funding; "
                        f"payout rows {payout_action}."
                    ),
                },
            )
            summary["repaired"] += 1
            summary["orders"].append(
                {
                    "order_id": int(order.id),
                    "order_no": str(order.bot_order_no or f"WEB-{order.id}"),
                    "vip_monthly_cash_amount": monthly_amount,
                    "payout_base_before": old_payout_base,
                    "payout_base_after": new_payout_base,
                    "payout_action": payout_action,
                }
            )

        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = [
    "REPAIR_VERSION",
    "MONTH_START",
    "MONTH_END",
    "VIP_MONTHLY_KEYS",
    "repair_november_vip_monthly_store_funding",
]
