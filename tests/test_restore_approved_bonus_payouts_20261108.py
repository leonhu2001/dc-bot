from __future__ import annotations

import json
import sqlite3
import sys

from scripts import restore_approved_bonus_payouts_20261108 as recovery


def _prepare(tmp_path):
    root = tmp_path
    current = root / "web_dashboard.db"
    snapshot = root / "old_web_dashboard.db"
    ddl = """
        CREATE TABLE web_orders(id INTEGER PRIMARY KEY, bot_order_no TEXT, status TEXT);
        INSERT INTO web_orders VALUES (306, 'MO20261104006','closed');
        CREATE TABLE order_reports (id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT);
        INSERT INTO order_reports VALUES (1, 306, 'approved');
        CREATE TABLE worker_payouts (
            id INTEGER PRIMARY KEY, order_id INTEGER, worker_discord_id TEXT,
            payout_status TEXT, paid_at TEXT,
            base_rate REAL, base_payout INTEGER,
            named_bonus_rate REAL, named_bonus_amount INTEGER,
            final_payout INTEGER, note TEXT
        );
        CREATE TABLE customer_service_payouts (
            id INTEGER PRIMARY KEY, order_id INTEGER, customer_service_discord_id TEXT,
            payout_status TEXT, paid_at TEXT, rate REAL, payout_amount INTEGER, note TEXT
        );
        CREATE TABLE admin_audit_logs(
            id INTEGER PRIMARY KEY, admin_discord_id TEXT, action TEXT,
            target_type TEXT, target_id TEXT, before_json TEXT,
            after_json TEXT, created_at TEXT
        );
    """
    with sqlite3.connect(snapshot) as db:
        db.executescript(ddl)
        db.execute(
            "INSERT INTO worker_payouts VALUES (8,306,'staff-a','unpaid',NULL,"
            "0.80,160,0,0,164,'分潤：基礎80%＋前月業績達5000T 2%')"
        )
        db.execute(
            "INSERT INTO customer_service_payouts VALUES (3,306,'cs','unpaid',NULL,"
            "0.04,8,'approved')"
        )
    with sqlite3.connect(current) as db:
        db.executescript(ddl)
        db.execute(
            "INSERT INTO worker_payouts VALUES (8,306,'staff-a','unpaid',NULL,"
            "0.80,160,0,0,160,'分潤：基礎80%')"
        )
        db.execute(
            "INSERT INTO customer_service_payouts VALUES (3,306,'cs','unpaid',NULL,"
            "0.05,10,'base')"
        )
        before = {
            "worker_payouts": [{
                "id": 8, "worker_discord_id": "staff-a",
                "final_payout": 164, "payout_status": "unpaid", "paid_at": None,
            }],
            "customer_service_payouts": [{
                "id": 3, "customer_service_discord_id": "cs",
                "payout_amount": 8, "payout_status": "unpaid", "paid_at": None,
            }],
        }
        after = {
            "worker_payouts": [{
                "id": 8, "worker_discord_id": "staff-a",
                "final_payout": 160, "payout_status": "unpaid", "paid_at": None,
            }],
            "customer_service_payouts": [{
                "id": 3, "customer_service_discord_id": "cs",
                "payout_amount": 10, "payout_status": "unpaid", "paid_at": None,
            }],
        }
        db.execute(
            "INSERT INTO admin_audit_logs VALUES (1, 'owner', "
            "'accounting_recalculate_unpaid_payouts', 'order', '306', ?, ?, '2026-11-08')",
            (json.dumps(before), json.dumps(after)),
        )
    return current, snapshot


def test_verified_restore_only_corrects_bonus_and_cs_from_same_approved_snapshot(
    tmp_path, monkeypatch
):
    current, snapshot = _prepare(tmp_path)
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            plan = recovery.evaluate(now, old, 306)
    assert plan["state"] == "ready"
    assert {(row["table"], row["from"], row["to"]) for row in plan["changes"]} == {
        ("worker_payouts", 160, 164),
        ("customer_service_payouts", 10, 8),
    }
    monkeypatch.setattr(recovery, "ROOT", tmp_path)
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    monkeypatch.setattr(sys, "argv", [
        "recovery", "--snapshot", str(snapshot), "--order-ids", "306", "--apply"
    ])
    assert recovery.main() == 0
    with sqlite3.connect(current) as db:
        assert db.execute("SELECT final_payout FROM worker_payouts").fetchone()[0] == 164
        assert db.execute("SELECT payout_amount FROM customer_service_payouts").fetchone()[0] == 8
        note = db.execute("SELECT note FROM worker_payouts").fetchone()[0]
        assert "前月業績達5000T 2%" in note
        assert db.execute(
            "SELECT COUNT(*) FROM admin_audit_logs "
            "WHERE action='restore_approved_bonus_from_verified_backup'"
        ).fetchone()[0] == 1
    assert list((tmp_path / "_archive").glob("approved_bonus_restore_*/*.db"))


def test_restore_blocks_any_paid_row_and_does_not_modify_database(tmp_path):
    current, snapshot = _prepare(tmp_path)
    with sqlite3.connect(current) as db:
        db.execute("UPDATE worker_payouts SET payout_status='paid' WHERE id=8")
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            result = recovery.evaluate(now, old, 306)
    assert result["state"] == "blocked"
    assert "已發放" in result["reason"]


def test_restore_matches_recreated_payout_ids_to_their_own_audit(tmp_path):
    current, snapshot = _prepare(tmp_path)
    # Base recalculation deletes and re-inserts the payouts, changing PKs.
    with sqlite3.connect(current) as db:
        db.execute("UPDATE worker_payouts SET id=18 WHERE id=8")
        db.execute("UPDATE customer_service_payouts SET id=13 WHERE id=3")
        before, after = db.execute(
            "SELECT before_json, after_json FROM admin_audit_logs WHERE id=1"
        ).fetchone()
        after = json.loads(after)
        after["worker_payouts"][0]["id"] = 18
        after["customer_service_payouts"][0]["id"] = 13
        db.execute("UPDATE admin_audit_logs SET after_json=? WHERE id=1",
                   (json.dumps(after),))
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            plan = recovery.evaluate(now, old, 306)
    assert plan["state"] == "ready"
    assert {(c["table"], c["id"], c["to"]) for c in plan["changes"]} == {
        ("worker_payouts", 18, 164),
        ("customer_service_payouts", 13, 8),
    }


def test_restore_rejects_regenerated_ids_not_present_in_latest_audit(tmp_path):
    current, snapshot = _prepare(tmp_path)
    with sqlite3.connect(current) as db:
        db.execute("UPDATE worker_payouts SET id=18 WHERE id=8")
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            plan = recovery.evaluate(now, old, 306)
    assert plan["state"] == "blocked"
    assert "ID" in plan["reason"]


def test_november_batch_discovery_only_selects_repaired_closed_orders(tmp_path):
    current, _ = _prepare(tmp_path)
    with sqlite3.connect(current) as db:
        db.execute("ALTER TABLE web_orders ADD COLUMN closed_at TEXT")
        db.execute("ALTER TABLE web_orders ADD COLUMN updated_at TEXT")
        db.execute("ALTER TABLE web_orders ADD COLUMN created_at TEXT")
        db.execute("UPDATE web_orders SET closed_at='2026-11-04 12:00:00'")
        db.execute("INSERT INTO web_orders "
                   "(id,bot_order_no,status,closed_at) VALUES "
                   "(307,'MO20261104007','closed','2026-11-04 13:00:00'),"
                   "(308,'MO20261030001','closed','2026-10-30 13:00:00')")
        db.execute("INSERT INTO admin_audit_logs "
                   "(id,admin_discord_id,action,target_type,target_id,"
                   "before_json,after_json,created_at) VALUES "
                   "(2,'owner','accounting_recalculate_unpaid_payouts',"
                   "'order','308','{}','{}','2026-11-09')")
        assert recovery.november_repair_order_ids(db) == [306]


def test_repeat_recovery_is_rejected_as_duplicate(tmp_path, monkeypatch):
    current, snapshot = _prepare(tmp_path)
    monkeypatch.setattr(recovery, "ROOT", tmp_path)
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE", "1")
    monkeypatch.setattr(sys, "argv", [
        "recovery", "--snapshot", str(snapshot), "--order-ids", "306", "--apply"
    ])
    assert recovery.main() == 0
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            plan = recovery.evaluate(now, old, 306)
    assert plan["state"] == "blocked"
    assert "重複" in plan["reason"]


def test_restore_rejects_bonus_note_from_different_worker(tmp_path):
    current, snapshot = _prepare(tmp_path)
    with sqlite3.connect(current) as db:
        before, after = db.execute(
            "SELECT before_json, after_json FROM admin_audit_logs WHERE id=1"
        ).fetchone()
        data = json.loads(before)
        data["worker_payouts"][0]["worker_discord_id"] = "other-staff"
        db.execute("UPDATE admin_audit_logs SET before_json=? WHERE id=1",
                   (json.dumps(data),))
    with recovery._open(current, readonly=True) as now:
        with recovery._open(snapshot, readonly=True) as old:
            plan = recovery.evaluate(now, old, 306)
    assert plan["state"] == "blocked"
    assert "名單" in plan["reason"]
