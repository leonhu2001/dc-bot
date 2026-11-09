#!/usr/bin/env python3
"""Read-only audit of every November 2026 closed, approved staff payout.

Reports whether an October >=5000T performer received the November 2%
bonus. This does not pay staff or change ledger records; ambiguous and paid
rows are flagged for manual review, never auto-corrected.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.one_companion_one_guard_payout import is_full_worker_payout_rule
from web.app.services.accounting_reconciliation_policy import (
    _is_legacy_snapshot, _rate_from_persisted_note,
)

BONUS_MARKERS = ("前月業績達5000T 2%", "前月已結算薪資達5000T 2%")
OCT_START, NOV_START = "2026-09-30 16:00:00", "2026-10-31 16:00:00"
DEC_START = "2026-11-30 16:00:00"


def _has_table(db: sqlite3.Connection, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _performance(db: sqlite3.Connection, worker_id: str) -> int:
    wages = db.execute(
        """
        SELECT COALESCE(SUM(p.final_payout),0)
        FROM worker_payouts p JOIN web_orders o ON o.id=p.order_id
        WHERE p.worker_discord_id=? AND o.status='closed'
          AND COALESCE(p.final_payout,0)>0
          AND COALESCE(o.closed_at,o.updated_at,o.created_at)>=?
          AND COALESCE(o.closed_at,o.updated_at,o.created_at)<?
        """, (worker_id, OCT_START, NOV_START)
    ).fetchone()[0]
    tips = 0
    if _has_table(db, "worker_tips"):
        tips = db.execute(
            """
            SELECT COALESCE(SUM(t.amount),0)
            FROM worker_tips t JOIN web_orders o ON o.id=t.order_id
            WHERE CAST(t.worker_discord_id AS TEXT)=? AND o.status='closed'
              AND t.payment_status='paid' AND COALESCE(t.amount,0)>0
              AND COALESCE(NULLIF(o.closed_at,''),NULLIF(o.updated_at,''),
                           NULLIF(o.created_at,''))>=?
              AND COALESCE(NULLIF(o.closed_at,''),NULLIF(o.updated_at,''),
                           NULLIF(o.created_at,''))<?
            """, (worker_id, OCT_START, NOV_START)
        ).fetchone()[0]
    return max(0, int(wages or 0) + int(tips or 0))


def _bonus_note(note: str) -> str:
    marker = "＋前月業績達5000T 2%"
    if "｜" in note:
        left, right = note.split("｜", 1)
        return left + marker + "｜" + right
    return note + marker


def assess_payout(note: str, gross_share: int, final_payout: int) -> dict:
    """Calculate only differences proven by a persisted, recognized payout note."""
    note = str(note or "")
    gross = max(0, int(gross_share or 0))
    actual = int(final_payout or 0)
    rate = _rate_from_persisted_note(note)
    if rate is None:
        return {"status": "needs_backup_review", "missing": None}
    note_expected = int(round(gross * rate))
    if note_expected != actual:
        return {"status": "amount_inconsistent", "missing": None,
                "note_expected": note_expected}
    if any(marker in note for marker in BONUS_MARKERS):
        return {"status": "already_has_bonus", "missing": 0}
    plus_rate = _rate_from_persisted_note(_bonus_note(note))
    if plus_rate is None:
        return {"status": "needs_backup_review", "missing": None}
    increase = max(0, int(round(gross * plus_rate)) - actual)
    return {"status": "missing_bonus" if increase else "capped_no_difference",
            "missing": increase, "expected_payout": actual + increase}


def audit(db: sqlite3.Connection) -> dict:
    required = ("web_orders", "worker_payouts", "order_reports")
    if any(not _has_table(db, name) for name in required):
        raise RuntimeError("缺少訂單、分潤或報單資料表，無法查核")
    report_cols = {row[1] for row in db.execute("PRAGMA table_info(order_reports)")}
    report_legacy = "COALESCE(is_legacy,0)" if "is_legacy" in report_cols else "0"
    rows = db.execute(
        """
        SELECT id, bot_order_no, status, order_rule_key, price_snapshot_json
        FROM web_orders
        WHERE status='closed'
          AND COALESCE(closed_at,updated_at,created_at)>=?
          AND COALESCE(closed_at,updated_at,created_at)<?
        ORDER BY id
        """, (NOV_START, DEC_START)
    ).fetchall()
    performance_cache: dict[str, int] = {}
    items = []
    for order in rows:
        report = db.execute(
            f"SELECT status, {report_legacy} AS is_legacy FROM order_reports "
            "WHERE order_id=? ORDER BY id DESC LIMIT 1", (order["id"],)
        ).fetchone()
        if (report is None or str(report["status"]).lower() != "approved"
                or report["is_legacy"] or
                _is_legacy_snapshot(order["price_snapshot_json"]) or
                is_full_worker_payout_rule(order["order_rule_key"])):
            continue
        staff = db.execute(
            "SELECT id, worker_discord_id, gross_share, final_payout, "
            "payout_status, paid_at, note FROM worker_payouts "
            "WHERE order_id=? ORDER BY id", (order["id"],)
        ).fetchall()
        for row in staff:
            worker_id = str(row["worker_discord_id"] or "")
            if not worker_id:
                continue
            if worker_id not in performance_cache:
                performance_cache[worker_id] = _performance(db, worker_id)
            performance = performance_cache[worker_id]
            if performance < 5000:
                continue
            detail = assess_payout(row["note"], row["gross_share"], row["final_payout"])
            status = detail["status"]
            if status == "missing_bonus" and (
                    str(row["payout_status"]).lower() != "unpaid"
                    or row["paid_at"] is not None):
                status = "paid_requires_manual_adjustment"
            items.append({
                "order_id": int(order["id"]),
                "order_no": order["bot_order_no"],
                "worker_id": worker_id,
                "october_performance": performance,
                "current_payout": int(row["final_payout"] or 0),
                "payout_status": str(row["payout_status"]),
                "bonus_status": status,
                "provable_missing": detail.get("missing"),
                "expected_if_note_trustworthy": detail.get("expected_payout"),
            })
    return {
        "month": "2026-11", "threshold": 5000, "bonus_rate": 0.02,
        "eligible_workers": sum(value >= 5000 for value in performance_cache.values()),
        "provable_unpaid_missing_total": sum(
            int(item["provable_missing"] or 0) for item in items
            if item["bonus_status"] == "missing_bonus"
        ),
        "needs_review_count": sum(
            item["bonus_status"] in (
                "needs_backup_review", "amount_inconsistent",
                "paid_requires_manual_adjustment",
            )
            for item in items
        ),
        "items": items,
    }


def main() -> int:
    path = ROOT / "web_dashboard.db"
    if not path.is_file():
        print(f"FAIL: 找不到 {path}", file=sys.stderr)
        return 2
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as db:
            db.row_factory = sqlite3.Row
            print(json.dumps(audit(db), ensure_ascii=False, indent=2))
        return 0
    except (sqlite3.Error, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
