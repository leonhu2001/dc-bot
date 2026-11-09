#!/usr/bin/env python3
"""Conservative, auditable repair for two verified November 2026 bonus losses.

Default is READ ONLY. --apply requires both services stopped and maintenance
opt-in. Repairs only specifically verified, approved, UNPAID worker and CS rows,
after validating dated pre-repair backups. All changes are atomic and backed up.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.payout import (
    CUSTOMER_SERVICE_PAYOUT_RATE,
    calculate_customer_service_payout,
    calculate_customer_service_payout_base_amount,
)
from web.app.services.accounting_reconciliation_policy import _rate_from_persisted_note

STAFF = "1029311167212036116"
PERFORMANCE = 13801
ACTION = "restore_november_bonus_verified_20261110"
SPECS = {
    298: {
        "order_no": "MO20261102001", "rule": "basic_tech_secret_single",
        "gross": 720, "current": 576, "old_gross": 620, "old": 508,
        "snapshot": "deploy_20261103_145019",
    },
    300: {
        "order_no": "MO20261103002", "rule": "basic_trial_1000",
        "gross": 450, "current": 360, "old_gross": 450, "old": 369,
        "snapshot": "deploy_20261108_135220",
    },
}


def connect(path: Path, *, readonly: bool = True) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"找不到已驗證的資料庫備份：{path}")
    value = f"file:{path}?mode=ro" if readonly else str(path)
    db = sqlite3.connect(value, uri=readonly, timeout=20)
    db.row_factory = sqlite3.Row
    return db


def one(db: sqlite3.Connection, table: str, where: str, params: tuple) -> dict:
    rows = [dict(r) for r in db.execute(
        f"SELECT * FROM {table} WHERE {where}", params
    ).fetchall()]
    if len(rows) != 1:
        raise RuntimeError(f"{table} 預期一筆但找到 {len(rows)} 筆，拒絕猜測")
    return rows[0]


def verified_note(db: sqlite3.Connection, order_id: int, spec: dict) -> str:
    path = ROOT / "_archive" / spec["snapshot"] / "web_dashboard.db"
    with connect(path) as old:
        order = one(old, "web_orders", "id=?", (order_id,))
        payout = one(
            old, "worker_payouts", "order_id=? AND worker_discord_id=?",
            (order_id, STAFF),
        )
    if (str(order.get("bot_order_no")) != spec["order_no"]
            or int(payout.get("gross_share") or 0) != spec["old_gross"]
            or int(payout.get("final_payout") or 0) != spec["old"]
            or str(payout.get("payout_status")) != "unpaid"
            or payout.get("paid_at") is not None):
        raise RuntimeError("修復前備份的訂單、員工、金額或未發放狀態不同")
    note = str(payout.get("note") or "")
    if ("前月業績達5000T 2%" not in note
            or f"前月業績 {PERFORMANCE}T" not in note
            or abs(float(_rate_from_persisted_note(note) or 0) - 0.82) > 1e-9):
        raise RuntimeError("原始備份無法證明這位員工的 2% 資格或分潤率")
    if int(round(spec["old_gross"] * 0.82)) != spec["old"]:
        raise RuntimeError("修復前分潤金額與 82% 不一致")
    return note


def evaluate(db: sqlite3.Connection, order_id: int) -> dict:
    spec = SPECS[order_id]
    result = {"order_id": order_id, "order_no": spec["order_no"], "state": "blocked"}
    try:
        existing = db.execute(
            "SELECT 1 FROM admin_audit_logs "
            "WHERE action=? AND target_type='order' AND target_id=? LIMIT 1",
            (ACTION, str(order_id)),
        ).fetchone()
        if existing:
            raise RuntimeError("已有本次補發稽核，禁止重複執行")
        order = one(db, "web_orders", "id=?", (order_id,))
        if (str(order.get("bot_order_no")) != spec["order_no"]
                or str(order.get("status")) != "closed"
                or str(order.get("order_rule_key")) != spec["rule"]):
            raise RuntimeError("訂單編號、結單狀態或原品項不一致")
        report = db.execute(
            "SELECT status FROM order_reports WHERE order_id=? ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if report is None or str(report["status"]).lower() != "approved":
            raise RuntimeError("未找到已核准報單")
        original_note = verified_note(db, order_id, spec)
        worker = one(
            db, "worker_payouts", "order_id=? AND worker_discord_id=?",
            (order_id, STAFF),
        )
        if (int(worker.get("gross_share") or 0) != spec["gross"]
                or int(worker.get("final_payout") or 0) != spec["current"]
                or str(worker.get("payout_status")) != "unpaid"
                or worker.get("paid_at") is not None
                or str(worker.get("note") or "").strip()):
            raise RuntimeError("目前的員工分潤已有變動、已發放或已有額外加成，禁止重補")
        overrides = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='worker_payout_overrides'"
        ).fetchone()
        if overrides and db.execute(
            "SELECT 1 FROM worker_payout_overrides "
            "WHERE order_id=? AND worker_discord_id=? LIMIT 1",
            (order_id, STAFF),
        ).fetchone():
            raise RuntimeError("存在手動指定分潤，不能覆蓋")
        target = int(round(spec["gross"] * 0.82))
        if target <= spec["current"]:
            raise RuntimeError("此筆已無額外分潤可補")
        base = int(order.get("payout_base_amount") or order.get("amount") or 0)
        if base <= 0:
            raise RuntimeError("訂單分潤基數無效")
        worker_rows = [dict(r) for r in db.execute(
            "SELECT * FROM worker_payouts WHERE order_id=?", (order_id,)
        )]
        total_before = sum(int(r.get("final_payout") or 0) for r in worker_rows)
        total_after = total_before + target - spec["current"]
        cs = one(db, "customer_service_payouts", "order_id=?", (order_id,))
        if (str(cs.get("payout_status")) != "unpaid"
                or cs.get("paid_at") is not None):
            raise RuntimeError("客服分潤已發放，不能改寫歷史金額")
        cs_basis = int(calculate_customer_service_payout_base_amount(
            payout_base_amount=base,
            price_snapshot_json=order.get("price_snapshot_json"),
        ))
        def calc_cs(total_worker: int) -> int:
            rate = min(1.0, total_worker / base)
            return int(round(calculate_customer_service_payout(
                cs_basis, CUSTOMER_SERVICE_PAYOUT_RATE,
                effective_worker_rate=rate,
            )))
        cs_before = calc_cs(total_before)
        cs_after = calc_cs(total_after)
        if int(cs.get("payout_amount") or 0) != cs_before:
            raise RuntimeError(
                f"客服原分潤 {cs.get('payout_amount')}T 與現行制度 "
                f"{cs_before}T 不符，需人工核對"
            )
        result.update(
            state="ready", worker_row_id=int(worker["id"]),
            cs_row_id=int(cs["id"]),
            from_worker=spec["current"], to_worker=target,
            worker_increase=target-spec["current"],
            from_cs=cs_before, to_cs=cs_after,
            cs_difference=cs_after-cs_before,
            cs_rate=(cs_after / cs_basis if cs_basis > 0 else 0.0),
            original_note=original_note,
        )
    except (RuntimeError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and os.environ.get("MW_ORDER_REPAIR_MAINTENANCE") != "1":
        print("FAIL: 必須停機並設定 MW_ORDER_REPAIR_MAINTENANCE=1", file=sys.stderr)
        return 2

    db = connect(ROOT / "web_dashboard.db", readonly=not args.apply)
    try:
        plans = [evaluate(db, oid) for oid in SPECS]
        ready = [p for p in plans if p["state"] == "ready"]
        total = sum(p["worker_increase"] for p in ready)
        print(json.dumps({
            "ready_count": len(ready), "blocked_count": len(plans)-len(ready),
            "total_worker_increase": total,
            "orders": plans,
        }, ensure_ascii=False, indent=2))
        if not args.apply:
            return 0 if len(ready) == len(SPECS) else 1
        if len(ready) != len(SPECS):
            print("FAIL: 有未核對完成的訂單，不更動任何薪資", file=sys.stderr)
            return 2
        backup_dir = ROOT / "_archive" / (
            "nov_bonus_298_300_before_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup = backup_dir / "web_dashboard.db"
        with sqlite3.connect(backup) as target:
            db.backup(target)

        db.execute("BEGIN IMMEDIATE")
        try:
            locked = [evaluate(db, oid) for oid in SPECS]
            if locked != plans:
                raise RuntimeError("加鎖後分潤、稽核或備份改變，全部回滾")
            for p in plans:
                cur = db.execute(
                    "UPDATE worker_payouts SET final_payout=?,note=? "
                    "WHERE id=? AND final_payout=? AND payout_status='unpaid' "
                    "AND paid_at IS NULL AND COALESCE(TRIM(note),'')=''",
                    (p["to_worker"], p["original_note"],
                     p["worker_row_id"], p["from_worker"]),
                )
                if cur.rowcount != 1:
                    raise RuntimeError("員工分潤寫入失敗，已回滾")
                cur = db.execute(
                    "UPDATE customer_service_payouts SET payout_amount=?,rate=? "
                    "WHERE id=? AND payout_amount=? AND payout_status='unpaid' "
                    "AND paid_at IS NULL",
                    (p["to_cs"], p["cs_rate"], p["cs_row_id"], p["from_cs"]),
                )
                if cur.rowcount != 1:
                    raise RuntimeError("客服分潤寫入失敗，已回滾")
                db.execute(
                    "INSERT INTO admin_audit_logs "
                    "(admin_discord_id,action,target_type,target_id,"
                    "before_json,after_json,created_at) "
                    "VALUES ('owner-offline',?,'order',?,?,?,?)",
                    (
                        ACTION, str(p["order_id"]),
                        json.dumps({"worker":p["from_worker"],"cs":p["from_cs"]}),
                        json.dumps({"worker":p["to_worker"],"cs":p["to_cs"]}),
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(json.dumps({
            "state":"applied", "total_worker_increase":total,
            "backup":str(backup), "orders":[p["order_id"] for p in plans],
        }, ensure_ascii=False, indent=2))
        return 0
    except (sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
