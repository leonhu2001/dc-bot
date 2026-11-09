from __future__ import annotations

import sqlite3

from scripts import audit_november_bonus_20261109 as audit


def test_audit_recognizes_missing_two_percent_and_existing_bonus():
    gap = audit.assess_payout(
        "分潤：基礎80%｜前月業績 5200T", 1000, 800
    )
    assert gap == {
        "status": "missing_bonus", "missing": 20, "expected_payout": 820,
    }
    assert audit.assess_payout(
        "分潤：基礎80%＋前月業績達5000T 2%", 1000, 820
    )["status"] == "already_has_bonus"
    assert audit.assess_payout(None, 1000, 800)["status"] == "needs_backup_review"
    assert audit.assess_payout(
        "分潤：基礎80%", 1000, 790
    )["status"] == "amount_inconsistent"


def test_audit_respects_normal_and_store_binding_caps():
    detail = audit.assess_payout(
        "分潤：基礎80%＋掛名3%＋直播2%＋綁店3%", 1000, 880
    )
    assert detail["status"] == "missing_bonus"
    assert detail["missing"] == 20
    assert detail["expected_payout"] == 900
    assert audit.assess_payout(
        "分潤：基礎80%＋掛名3%＋直播2%＋前月業績達5000T 2%＋綁店3%",
        1000, 900,
    )["status"] == "already_has_bonus"


def test_readonly_november_audit_flags_paid_gap_without_changing_rows():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE web_orders(
            id INTEGER PRIMARY KEY, bot_order_no TEXT, status TEXT,
            order_rule_key TEXT, price_snapshot_json TEXT,
            created_at TEXT, updated_at TEXT, closed_at TEXT
        );
        CREATE TABLE worker_payouts(
            id INTEGER PRIMARY KEY, order_id INTEGER, worker_discord_id TEXT,
            gross_share INTEGER, final_payout INTEGER, payout_status TEXT,
            paid_at TEXT, note TEXT
        );
        CREATE TABLE order_reports(
            id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT,
            is_legacy INTEGER
        );
        INSERT INTO web_orders VALUES
          (1,'MO20261010001','closed',NULL,'{}',
           '2026-10-10 00:00:00','2026-10-10 00:00:00','2026-10-10 00:00:00'),
          (2,'MO20261104001','closed',NULL,'{}',
           '2026-11-04 00:00:00','2026-11-04 00:00:00','2026-11-04 00:00:00'),
          (3,'MO20261104002','closed',NULL,'{}',
           '2026-11-04 01:00:00','2026-11-04 01:00:00','2026-11-04 01:00:00');
        INSERT INTO worker_payouts VALUES
          (1,1,'staff-a',6500,5200,'paid','2026-10-15',NULL),
          (2,2,'staff-a',500,400,'unpaid',NULL,'分潤：基礎80%'),
          (3,3,'staff-a',1000,800,'paid','2026-11-05','分潤：基礎80%');
        INSERT INTO order_reports VALUES
          (1,2,'approved',0),(2,3,'approved',0);
    """)
    result = audit.audit(db)
    assert result["eligible_workers"] == 1
    assert result["provable_unpaid_missing_total"] == 10
    by_order = {item["order_id"]: item for item in result["items"]}
    assert by_order[2]["bonus_status"] == "missing_bonus"
    assert by_order[2]["provable_missing"] == 10
    assert by_order[3]["bonus_status"] == "paid_requires_manual_adjustment"
    assert result["needs_review_count"] == 1
    assert db.execute(
        "SELECT final_payout FROM worker_payouts WHERE id=3"
    ).fetchone()[0] == 800
    db.close()
