from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import services.vip_timer as vip_timer


@pytest.fixture()
def timer_env(tmp_path, monkeypatch):
    db_path = tmp_path / "vip-timer.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    monkeypatch.setattr(vip_timer, "SessionLocal", local)

    rules = {
        "hour_a": SimpleNamespace(
            key="hour_a",
            label="玩法 A",
            category="steam",
            pricing_type="hourly",
            price=300,
            player_count_enabled=False,
            min_player_count=1,
            max_player_count=1,
            allow_specify=False,
        ),
        "hour_b": SimpleNamespace(
            key="hour_b",
            label="玩法 B",
            category="steam",
            pricing_type="hourly",
            price=500,
            player_count_enabled=False,
            min_player_count=1,
            max_player_count=1,
            allow_specify=False,
        ),
    }
    monkeypatch.setattr(vip_timer, "ORDER_RULES", rules)
    monkeypatch.setattr(vip_timer, "is_order_product_active", lambda key: True)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT,
                amount INTEGER DEFAULT 0,
                original_amount INTEGER DEFAULT 0,
                payout_base_amount INTEGER DEFAULT 0,
                customer_pay_amount INTEGER DEFAULT 0,
                payment_method TEXT,
                price_snapshot_json TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                price_snapshot_json TEXT,
                updated_at TEXT
            )
        """))
        for order_id in range(1, 10):
            conn.execute(
                text("INSERT INTO web_orders(id, status) VALUES (:id, 'accepted_pending_pay')"),
                {"id": order_id},
            )
            conn.execute(
                text("INSERT INTO order_acceptance_meta(order_id) VALUES (:id)"),
                {"id": order_id},
            )

    vip_timer.ensure_vip_timer_tables()
    return SimpleNamespace(engine=engine, SessionLocal=local, rules=rules)


def _create_session(timer_env, *, order_id: int, customer_id: str, rule_key: str = "hour_a"):
    db = timer_env.SessionLocal()
    try:
        vip_timer.create_vip_timer_session(
            db,
            order_id=order_id,
            customer_id=customer_id,
            initial_rule_key=rule_key,
        )
        db.commit()
    finally:
        db.close()


def test_mixed_segment_total_rounds_once(timer_env):
    _create_session(timer_env, order_id=1, customer_id="1001")
    now = vip_timer.utc_iso(datetime(2026, 1, 1, tzinfo=timezone.utc))

    with timer_env.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO vip_timer_segments(
                order_id, seq, rule_key, rule_label, category_label,
                hourly_rate, started_at, ended_at, billable_seconds,
                staff_ids_json, created_at, updated_at
            ) VALUES
                (1, 1, 'hour_a', '玩法 A', 'STEAM遊戲 陪玩', 300, :now, :now, 1800, '[]', :now, :now),
                (1, 2, 'hour_b', '玩法 B', 'STEAM遊戲 陪玩', 500, :now, :now, 1800, '[]', :now, :now)
        """), {"now": now})

    amount, seconds = vip_timer.calculate_total(1)
    assert seconds == 3600
    assert amount == 400


def test_pause_time_is_not_billed(timer_env, monkeypatch):
    _create_session(timer_env, order_id=2, customer_id="1002")
    clock = [datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(vip_timer, "utc_now", lambda: clock[0])

    vip_timer.start_timer(2, "staff-1", ["staff-1"])
    clock[0] += timedelta(minutes=10)
    vip_timer.pause_timer(2, "staff-1")

    clock[0] += timedelta(hours=1)
    vip_timer.resume_timer(2, "staff-1")

    clock[0] += timedelta(minutes=10)
    result = vip_timer.end_timer(2, "staff-1")

    assert result["total_seconds"] == 20 * 60
    assert result["final_amount"] == 100


def test_segment_keeps_rate_snapshot_after_catalog_price_changes(timer_env, monkeypatch):
    _create_session(timer_env, order_id=3, customer_id="1003")
    clock = [datetime(2026, 1, 2, 8, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(vip_timer, "utc_now", lambda: clock[0])

    vip_timer.start_timer(3, "staff-1", ["staff-1"])
    timer_env.rules["hour_a"].price = 999
    clock[0] += timedelta(hours=1)
    result = vip_timer.end_timer(3, "staff-1")

    assert result["total_seconds"] == 3600
    assert result["final_amount"] == 300
    assert vip_timer.list_segments(3)[0]["hourly_rate"] == 300


def test_customer_cannot_open_second_timer_order(timer_env):
    _create_session(timer_env, order_id=4, customer_id="same-customer")

    db = timer_env.SessionLocal()
    try:
        with pytest.raises(ValueError, match="已有一張"):
            vip_timer.create_vip_timer_session(
                db,
                order_id=5,
                customer_id="same-customer",
                initial_rule_key="hour_b",
            )
    finally:
        db.rollback()
        db.close()


def test_inactive_source_rule_is_rejected(timer_env, monkeypatch):
    monkeypatch.setattr(vip_timer, "is_order_product_active", lambda key: False)
    with pytest.raises(ValueError, match="已下架"):
        vip_timer.rule_snapshot("hour_a")
