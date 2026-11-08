#!/usr/bin/env python3
"""Conservative recovery of approved 2%-bonus payouts from a VPS database backup.

READ ONLY by default. Never guesses new payouts and never touches paid records.
Requires the previous approved amounts to match BOTH the admin repair audit
(before/after) and an explicit pre-repair SQLite snapshot.
Run only in maintenance mode with both Bot and Web stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BONUS_MARKERS = ("前月業績達5000T 2%", "前月已結算薪資達5000T 2%")
WORKER_FIELDS = (
    "base_rate", "base_payout", "named_bonus_rate", "named_bonus_amount",
    "final_payout", "note",
)
CS_FIELDS = ("rate", "payout_amount", "note")


def _open(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"資料庫不存在：{path}")
    uri = f"file:{path}?mode=ro" if readonly else str(path)
    db = sqlite3.connect(uri, uri=readonly, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _as_json(value: str) -> dict:
    try:
        obj = json.loads(str(value or "{}"))
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _rows(db: sqlite3.Connection, table: str, order_id: int) -> dict[int, dict]:
    return {
        int(r["id"]): dict(r)
        for r in db.execute(
            f"SELECT * FROM {table} WHERE order_id=? ORDER BY id", (order_id,)
        )
    }


def _audit_rows(data: dict, key: str) -> dict[int, dict]:
    return {
        int(row["id"]): row
        for row in (data.get(key) or [])
        if isinstance(row, dict) and row.get("id") is not None
    }


def evaluate(current: sqlite3.Connection, snapshot: sqlite3.Connection, order_id: int) -> dict:
    result = {"order_id": int(order_id), "state": "blocked"}
    order = current.execute(
        "SELECT id, bot_order_no, status FROM web_orders WHERE id=?", (order_id,)
    ).fetchone()
    if order is None:
        result["reason"] = "訂單不存在"
        return result
    result["order_no"] = order["bot_order_no"]
    if str(order["status"]).lower() != "closed":
        result["reason"] = "僅接受已結單且已核准報單"
        return result
    report = current.execute(
        "SELECT status FROM order_reports WHERE order_id=? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    if report is None or str(report["status"]).lower() != "approved":
        result["reason"] = "找不到已核准的報單"
        return result
    audits = current.execute(
        "SELECT id, before_json, after_json FROM admin_audit_logs "
        "WHERE action='accounting_recalculate_unpaid_payouts' AND target_type='order' "
        "AND target_id=? ORDER BY id DESC", (str(order_id),)
    ).fetchall()
    if not audits:
        result["reason"] = "缺少修復前後稽核，無法證明原始金額"
        return result
    # The latest repair must match today's rows exactly. Earlier audit records
    # are not eligible, as an intermediate edit could have happened afterwards.
    audit = audits[0]
    before, after = _as_json(audit["before_json"]), _as_json(audit["after_json"])
    result["repair_audit_id"] = int(audit["id"])
    pairs = (
        ("worker_payouts", WORKER_FIELDS, "final_payout"),
        ("customer_service_payouts", CS_FIELDS, "payout_amount"),
    )
    changes = []
    saw_previous_bonus = False
    saw_worker_decrease = False
    for table, fields, money_field in pairs:
        now_rows = _rows(current, table, order_id)
        old_rows = _rows(snapshot, table, order_id)
        before_rows = _audit_rows(before, table)
        after_rows = _audit_rows(after, table)
        if not now_rows or now_rows.keys() != old_rows.keys() or now_rows.keys() != before_rows.keys() or now_rows.keys() != after_rows.keys():
            result["reason"] = f"{table} 筆數或主鍵與備份/稽核不同"
            return result
        for row_id, now_row in now_rows.items():
            old_row = old_rows[row_id]
            before_row, after_row = before_rows[row_id], after_rows[row_id]
            if (str(now_row["payout_status"]).lower() != "unpaid"
                    or now_row["paid_at"] is not None):
                result["reason"] = f"{table} #{row_id} 已發放或付款狀態不安全"
                return result
            if (str(old_row["payout_status"]).lower() != "unpaid"
                    or old_row["paid_at"] is not None):
                result["reason"] = f"{table} #{row_id} 備份不是未發放狀態"
                return result
            identity_col = (
                "worker_discord_id" if table == "worker_payouts"
                else "customer_service_discord_id"
            )
            if str(now_row[identity_col]) != str(old_row[identity_col]):
                result["reason"] = f"{table} #{row_id} 身分不同"
                return result
            old_amount, now_amount = int(old_row[money_field]), int(now_row[money_field])
            if (old_amount != int(before_row[money_field])
                    or now_amount != int(after_row[money_field])):
                result["reason"] = f"{table} #{row_id} 無法驗證修復前後金額"
                return result
            if old_row[money_field] != now_row[money_field]:
                changes.append({
                    "table": table, "id": row_id, "from": now_amount,
                    "to": old_amount, "fields": fields,
                    "values": {field: old_row[field] for field in fields},
                })
            if table == "worker_payouts":
                if old_amount > now_amount:
                    saw_worker_decrease = True
                if any(marker in str(old_row["note"] or "") for marker in BONUS_MARKERS):
                    saw_previous_bonus = True
    if not saw_worker_decrease or not saw_previous_bonus:
        result["reason"] = "不符合額外2%曾被基礎重算降低的條件"
        return result
    if not changes:
        result["reason"] = "已無需復原"
        return result
    result["state"] = "ready"
    result["changes"] = changes
    return result


def backup_current(current: sqlite3.Connection, root: Path) -> Path:
    destination = root / "_archive" / (
        "approved_bonus_restore_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "web_dashboard.db"
    with sqlite3.connect(target) as copy:
        current.backup(copy)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot", type=Path, required=True,
        help="修復前資料庫備份，例如 _archive/deploy_.../web_dashboard.db",
    )
    parser.add_argument("--order-ids", type=int, nargs="+", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and os.environ.get("MW_ORDER_REPAIR_MAINTENANCE") != "1":
        print("FAIL: --apply 須停機且設定 MW_ORDER_REPAIR_MAINTENANCE=1", file=sys.stderr)
        return 2

    path = ROOT / "web_dashboard.db"
    current = _open(path, readonly=not args.apply)
    snapshot = _open(args.snapshot.resolve(), readonly=True)
    try:
        order_ids = sorted(set(args.order_ids))
        plans = [evaluate(current, snapshot, order_id) for order_id in order_ids]
        if not args.apply:
            print(json.dumps(plans, ensure_ascii=False, indent=2, default=str))
            return 0 if all(x["state"] == "ready" for x in plans) else 1
        if any(x["state"] != "ready" for x in plans):
            raise RuntimeError("存在不符合安全條件的訂單；沒有復原任何金額")
        backup_path = backup_current(current, ROOT)
        current.execute("BEGIN IMMEDIATE")
        try:
            # Re-check after acquiring write lock; abort the entire batch on drift.
            plans = [evaluate(current, snapshot, order_id) for order_id in order_ids]
            if any(x["state"] != "ready" for x in plans):
                raise RuntimeError("鎖定後條件變動，已回滾")
            for plan in plans:
                before = {}
                after = {}
                for change in plan["changes"]:
                    table = change["table"]
                    row_id = change["id"]
                    before[f"{table}:{row_id}"] = change["from"]
                    after[f"{table}:{row_id}"] = change["to"]
                    assignments = ", ".join(f"{col}=?" for col in change["fields"])
                    sql = f"UPDATE {table} SET {assignments} WHERE id=? AND payout_status='unpaid' AND paid_at IS NULL"
                    cursor = current.execute(
                        sql, (*[change["values"][col] for col in change["fields"]], row_id)
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(f"{table} #{row_id} 復原時狀態改變")
                current.execute(
                    "INSERT INTO admin_audit_logs "
                    "(admin_discord_id, action, target_type, target_id, "
                    "before_json, after_json, created_at) "
                    "VALUES (?, ?, 'order', ?, ?, ?, ?)",
                    (
                        "owner-offline", "restore_approved_bonus_from_verified_backup",
                        str(plan["order_id"]),
                        json.dumps(before, ensure_ascii=False),
                        json.dumps(after, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
            current.commit()
        except Exception:
            current.rollback()
            raise
        print(json.dumps({
            "state": "applied", "orders": order_ids,
            "current_backup": str(backup_path),
            "changes": [
                {"order_id": p["order_id"], "rows": [
                    {k: c[k] for k in ("table", "id", "from", "to")}
                    for c in p["changes"]
                ]} for p in plans
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        snapshot.close()
        current.close()


if __name__ == "__main__":
    raise SystemExit(main())
