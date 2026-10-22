from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer_roster_payout as payout
from shared.db import Base
from shared.models import WebOrder


def _legacy_timer_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-timer-roster.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE vip_timer_sessions (
                order_id INTEGER PRIMARY KEY,
                status TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE vip_timer_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                rule_key TEXT,
                hourly_rate INTEGER NOT NULL,
                billable_seconds INTEGER NOT NULL,
                staff_ids_json TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE vip_timer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                action TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))
    return engine, Local


def _create_order(Local) -> int:
    db = Local()
    try:
        order = WebOrder(
            category="VIP 自由計時",
            item="歷史空名單測試",
            quantity=1,
            amount=900,
            payout_base_amount=900,
            customer_pay_amount=900,
            status="closed",
        )
        db.add(order)
        db.flush()
        order_id = int(order.id)
        db.execute(
            text("INSERT INTO vip_timer_sessions(order_id,status) VALUES (:id,'paid')"),
            {"id": order_id},
        )
        db.execute(text("""
            INSERT INTO vip_timer_segments(
                order_id,seq,rule_key,hourly_rate,billable_seconds,staff_ids_json
            ) VALUES (:id,1,'legacy_rule',900,3600,'[]')
        """), {"id": order_id})
        db.execute(text("""
            INSERT INTO order_acceptance_claims(
                order_id,staff_discord_id,staff_display_name,is_active
            ) VALUES
                (:id,'A','Alpha',1),
                (:id,'B','Beta',1)
        """), {"id": order_id})
        db.commit()
        return order_id
    finally:
        db.close()


def test_empty_legacy_segment_recovers_static_acceptance_roster(tmp_path):
    _, Local = _legacy_timer_db(tmp_path)
    order_id = _create_order(Local)

    db = Local()
    try:
        shares = payout._raw_worker_shares(order_id, db)
        assert shares == {"A": Decimal("450"), "B": Decimal("450")}

        order = db.get(WebOrder, order_id)
        plan = payout._worker_payout_plan(db, order)
        assert set(plan) == {"A", "B"}
        assert int(plan["A"]["gross_share"]) == 450
        assert int(plan["B"]["gross_share"]) == 450
        assert int(plan["A"]["final_payout"]) == 360
        assert int(plan["B"]["final_payout"]) == 360
    finally:
        db.close()


def test_empty_legacy_segment_does_not_guess_after_roster_change(tmp_path):
    _, Local = _legacy_timer_db(tmp_path)
    order_id = _create_order(Local)

    db = Local()
    try:
        db.execute(
            text("INSERT INTO vip_timer_events(order_id,action) VALUES (:id,'roster_change')"),
            {"id": order_id},
        )
        db.commit()
    finally:
        db.close()

    db = Local()
    try:
        assert payout._raw_worker_shares(order_id, db) == {}
    finally:
        db.close()


def test_empty_legacy_segment_does_not_guess_with_inactive_claim(tmp_path):
    _, Local = _legacy_timer_db(tmp_path)
    order_id = _create_order(Local)

    db = Local()
    try:
        db.execute(text("""
            INSERT INTO order_acceptance_claims(
                order_id,staff_discord_id,staff_display_name,is_active
            ) VALUES (:id,'OLD','Old Worker',0)
        """), {"id": order_id})
        db.commit()
    finally:
        db.close()

    db = Local()
    try:
        assert payout._raw_worker_shares(order_id, db) == {}
    finally:
        db.close()
