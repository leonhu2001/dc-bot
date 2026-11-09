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


def _identity(table: str, row: dict) -> str:
    field = ("worker_discord_id" if table == "worker_payouts"
             else "customer_service_discord_id")
    identity = str(row.get(field) or "").strip()
    if not identity:
        raise ValueError(f"{table} 缺少 {field}")
    return identity


def _rows(db: sqlite3.Connection, table: str, order_id: int) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for record in db.execute(
        f"SELECT * FROM {table} WHERE order_id=? ORDER BY id", (order_id,)
    ):
        row = dict(record)
        identity = _identity(table, row)
        if identity in result:
            raise ValueError(f"{table} 接單身分重複：{identity}")
        result[identity] = row
    return result


def _audit_rows(data: dict, table: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in (data.get(table) or []):
        if not isinstance(row, dict) or row.get("id") is None:
            raise ValueError(f"{table} 稽核內容不完整")
        identity = _identity(table, row)
        if identity in result:
            raise ValueError(f"{table} 稽核身分重複：{identity}")
        result[identity] = row
    return result


def november_repair_order_ids(db: sqlite3.Connection) -> list[int]:
    """UTC bounds for November 2026 in Asia/Taipei (no timezone ambiguity)."""
    return [
        int(row[0]) for row in db.execute(
            """
            SELECT DISTINCT o.id
            FROM web_orders o
            JOIN admin_audit_logs a
              ON a.target_type='order'
             AND a.action='accounting_recalculate_unpaid_payouts'
             AND a.target_id=CAST(o.id AS TEXT)
            WHERE o.status='closed'
              AND COALESCE(o.closed_at, o.updated_at, o.created_at)
                    >= '2026-10-31 16:00:00'
              AND COALESCE(o.closed_at, o.updated_at, o.created_at)
                    < '2026-11-30 16:00:00'
            ORDER BY o.id
            """
        )
    ]


def evaluate(current: sqlite3.Connection, snapshot: sqlite3.Connection, order_id: int) -> dict:
    result = {"order_id": int(order_id), "state": "blocked"}
    order = current.execute(
        "SELECT id, bot_order_no, status FROM web_orders WHERE id=?", (order_id,)
    ).fetchone()
    if order is None:
        result["reason"] = "訂單不存在"
        return result
    result["order_no"] = order["bot_order_no"]
    already_restored = current.execute(
        "SELECT 1 FROM admin_audit_logs "
        "WHERE action='restore_approved_bonus_from_verified_backup' "
        "AND target_type='order' AND target_id=? LIMIT 1",
        (str(order_id),),
    ).fetchone()
    if already_restored:
        result["reason"] = "已有額外獎金復原稽核，禁止重複補發"
        return result
    original_order = snapshot.execute(
        "SELECT bot_order_no FROM web_orders WHERE id=?", (order_id,)
    ).fetchone()
    if original_order is None or str(original_order["bot_order_no"]) != str(order["bot_order_no"]):
        result["reason"] = "備份的訂單編號不一致"
        return result
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
    saw_verified_bonus_loss = False
    for table, fields, money_field in pairs:
        try:
            now_rows = _rows(current, table, order_id)
            old_rows = _rows(snapshot, table, order_id)
            before_rows = _audit_rows(before, table)
            after_rows = _audit_rows(after, table)
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
        if (not now_rows or now_rows.keys() != old_rows.keys()
                or now_rows.keys() != before_rows.keys()
                or now_rows.keys() != after_rows.keys()):
            result["reason"] = f"{table} 人員名單與備份/稽核不同，禁止猜測復原"
            return result
        for identity, now_row in now_rows.items():
            old_row = old_rows[identity]
            before_row, after_row = before_rows[identity], after_rows[identity]
            row_id = int(now_row["id"])
            # Generic recalculation deletes and reinserts payout rows. IDs can
            # differ before/after, but each version must match its OWN audit.
            if (int(old_row["id"]) != int(before_row["id"])
                    or row_id != int(after_row["id"])):
                result["reason"] = f"{table} {identity} 的資料列 ID 與稽核不一致"
                return result
            for label, record in (
                ("目前", now_row), ("修復前備份", old_row),
                ("稽核修復前", before_row), ("稽核修復後", after_row),
            ):
                if (str(record.get("payout_status")).lower() != "unpaid"
                        or record.get("paid_at") is not None):
                    result["reason"] = f"{table} {identity} {label}已發放或狀態不安全"
                    return result
            if "手動指定分潤" in str(now_row.get("note") or ""):
                result["reason"] = f"{table} {identity} 有手動指定分潤"
                return result
            old_amount, now_amount = int(old_row[money_field]), int(now_row[money_field])
            if (old_amount != int(before_row[money_field])
                    or now_amount != int(after_row[money_field])):
                result["reason"] = f"{table} {identity} 無法驗證修復前後金額"
                return result
            if table == "worker_payouts":
                if old_amount < now_amount:
                    result["reason"] = f"{table} {identity} 修復後金額反而增加"
                    return result
                if (old_amount > now_amount
                        and any(marker in str(old_row.get("note") or "")
                                for marker in BONUS_MARKERS)):
                    saw_verified_bonus_loss = True
            if old_amount != now_amount or any(
                    old_row[field] != now_row[field] for field in fields):
                changes.append({
                    "table": table, "id": row_id, "from": now_amount,
                    "to": old_amount, "fields": fields,
                    "values": {field: old_row[field] for field in fields},
                })
    if not saw_verified_bonus_loss:
        result["reason"] = "未找到同一位員工確實被重算減少的前月2%獎金"
        return result
    if not changes:
        result["reason"] = "已無需復原"
        return result
    result["state"] = "ready"
    result["changes"] = changes
    return result


def _candidate_snapshots(root: Path, explicit: Path | None) -> list[Path]:
    if explicit is not None:
        return [explicit.resolve()]
    archive = root / "_archive"
    return sorted(
        (path for path in archive.glob("deploy_*/web_dashboard.db") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _plan_from_snapshots(
    current: sqlite3.Connection, snapshot_paths: list[Path], order_id: int
) -> dict:
    for path in snapshot_paths:
        try:
            with _open(path, readonly=True) as old:
                plan = evaluate(current, old, order_id)
        except sqlite3.Error:
            continue  # A damaged/incomplete backup is never an authority.
        if plan["state"] == "ready":
            plan["snapshot_path"] = str(path)
            return plan
    return {
        "order_id": int(order_id), "state": "blocked",
        "reason": f"找不到與最近一次重算稽核相符的修復前備份（已查 {len(snapshot_paths)} 份）",
    }


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
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument(
        "--snapshot", type=Path,
        help="修復前資料庫備份，例如 _archive/deploy_.../web_dashboard.db",
    )
    sources.add_argument(
        "--auto-archives", action="store_true",
        help="自動逐一比對 _archive/deploy_*/web_dashboard.db 備份",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--order-ids", type=int, nargs="+")
    scope.add_argument("--all-november", action="store_true",
                       help="掃描11月已結單且有基本分潤重算稽核的訂單")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and os.environ.get("MW_ORDER_REPAIR_MAINTENANCE") != "1":
        print("FAIL: --apply 須停機且設定 MW_ORDER_REPAIR_MAINTENANCE=1", file=sys.stderr)
        return 2

    path = ROOT / "web_dashboard.db"
    current = _open(path, readonly=not args.apply)
    try:
        snapshot_paths = _candidate_snapshots(ROOT, args.snapshot)
        if not snapshot_paths:
            raise RuntimeError("沒有找到任何部署前備份，拒絕猜測分潤")
        order_ids = (november_repair_order_ids(current) if args.all_november
                     else sorted(set(args.order_ids)))
        plans = [_plan_from_snapshots(current, snapshot_paths, order_id)
                 for order_id in order_ids]
        ready = [plan for plan in plans if plan["state"] == "ready"]
        blocked = [plan for plan in plans if plan["state"] != "ready"]
        print(json.dumps({
            "ready_count": len(ready), "blocked_count": len(blocked),
            "total_worker_increase": sum(
                change["to"] - change["from"]
                for plan in ready for change in plan["changes"]
                if change["table"] == "worker_payouts"
            ),
            "orders": plans,
        }, ensure_ascii=False, indent=2, default=str))
        if not args.apply:
            return 0 if ready else 1
        if blocked and not args.all_november:
            raise RuntimeError("指定訂單有不安全項目，沒有復原任何金額")
        if not ready:
            raise RuntimeError("沒有可安全復原的訂單；未改動資料")
        # Auto-discovery deliberately skips unsafe/non-matching orders and
        # reports them for manual investigation instead of guessing payouts.
        order_ids = [p["order_id"] for p in ready]
        plans = ready
        backup_path = backup_current(current, ROOT)
        current.execute("BEGIN IMMEDIATE")
        try:
            # Re-check after acquiring write lock; abort the entire batch on drift.
            verified = []
            for plan in plans:
                with _open(Path(plan["snapshot_path"]), readonly=True) as old:
                    locked = evaluate(current, old, plan["order_id"])
                if locked["state"] != "ready" or locked["changes"] != plan["changes"]:
                    raise RuntimeError("鎖定後資料或備份變動，已回滾")
                verified.append(locked)
            if len(verified) != len(order_ids):
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
            "skipped_unsafe_orders": blocked,
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
        current.close()


if __name__ == "__main__":
    raise SystemExit(main())
