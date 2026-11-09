from __future__ import annotations

import sqlite3
import sys

from scripts import repair_nov_bonus_two_orders_20261110 as repair


def _create(path, current: bool):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE web_orders(
                id INTEGER PRIMARY KEY,bot_order_no TEXT,status TEXT,
                order_rule_key TEXT,payout_base_amount INTEGER,
                amount INTEGER,price_snapshot_json TEXT
            );
            CREATE TABLE worker_payouts(
                id INTEGER PRIMARY KEY,order_id INTEGER,worker_discord_id TEXT,
                gross_share INTEGER,final_payout INTEGER,base_rate REAL,
                payout_status TEXT,paid_at TEXT,note TEXT
            );
            CREATE TABLE customer_service_payouts(
                id INTEGER PRIMARY KEY,order_id INTEGER,rate REAL,
                payout_amount INTEGER,payout_status TEXT,paid_at TEXT
            );
            CREATE TABLE order_reports(
                id INTEGER PRIMARY KEY,order_id INTEGER,status TEXT
            );
            CREATE TABLE admin_audit_logs(
                id INTEGER PRIMARY KEY,admin_discord_id TEXT,action TEXT,
                target_type TEXT,target_id TEXT,before_json TEXT,
                after_json TEXT,created_at TEXT
            );
            INSERT INTO web_orders VALUES
                (298,'MO20261102001','closed','basic_tech_secret_single',
                1440,1240,'{}'),
                (300,'MO20261103002','closed','basic_trial_1000',
                900,900,'{}');
            INSERT INTO order_reports VALUES
                (1,298,'approved'),(2,300,'approved');
        """)
        if current:
            db.executescript(f"""
                INSERT INTO worker_payouts VALUES
                  (1,298,'{repair.STAFF}',720,576,.8,'unpaid',NULL,NULL),
                  (2,298,'another-worker',720,576,.8,'unpaid',NULL,NULL),
                  (3,300,'{repair.STAFF}',450,360,.8,'unpaid',NULL,NULL),
                  (4,300,'another-worker',450,360,.8,'unpaid',NULL,NULL);
                INSERT INTO customer_service_payouts VALUES
                  (5,298,.05,72,'unpaid',NULL),
                  (6,300,.05,45,'unpaid',NULL);
            """)
        else:
            db.executescript(f"""
                INSERT INTO worker_payouts VALUES
                  (1,298,'{repair.STAFF}',620,508,.8,'unpaid',NULL,
                   '分潤：基礎80%＋前月業績達5000T 2%｜前月業績 13801T'),
                  (3,300,'{repair.STAFF}',450,369,.8,'unpaid',NULL,
                   '分潤：基礎80%＋前月業績達5000T 2%｜前月業績 13801T');
            """)


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(repair, "ROOT", tmp_path)
    current = tmp_path / "web_dashboard.db"
    _create(current, True)
    for spec in repair.SPECS.values():
        snap_dir = tmp_path / "_archive" / spec["snapshot"]
        snap_dir.mkdir(parents=True)
        _create(snap_dir / "web_dashboard.db", False)
    return current


def test_bonus_298_300_uses_current_gross_and_verified_old_bonus(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    with repair.connect(path) as db:
        results = [repair.evaluate(db, oid) for oid in (298,300)]
    assert all(x["state"] == "ready" for x in results)
    assert [(x["from_worker"],x["to_worker"]) for x in results] == [
        (576,590),(360,369),
    ]
    assert sum(x["worker_increase"] for x in results) == 23
    assert [(x["from_cs"],x["to_cs"]) for x in results] == [
        (72,68),(45,43),
    ]


def test_bonus_repair_records_backup_and_blocks_repeat(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE","1")
    monkeypatch.setattr(sys,"argv",["repair","--apply"])
    assert repair.main() == 0
    with repair.connect(path) as db:
        assert [row[0] for row in db.execute(
            "SELECT final_payout FROM worker_payouts WHERE id IN (1,3) ORDER BY id"
        )] == [590,369]
        assert [row[0] for row in db.execute(
            "SELECT payout_amount FROM customer_service_payouts ORDER BY id"
        )] == [68,43]
        assert db.execute(
            "SELECT COUNT(*) FROM admin_audit_logs WHERE action=?",
            (repair.ACTION,),
        ).fetchone()[0] == 2
    assert repair.main() == 2


def test_bonus_repair_refuses_paid_or_changed_rows(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE worker_payouts SET payout_status='paid' WHERE id=3"
        )
    with repair.connect(path) as db:
        assert repair.evaluate(db,300)["state"] == "blocked"
    monkeypatch.setenv("MW_ORDER_REPAIR_MAINTENANCE","1")
    monkeypatch.setattr(sys,"argv",["repair","--apply"])
    assert repair.main() == 2
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT final_payout FROM worker_payouts WHERE id=1"
        ).fetchone()[0] == 576
