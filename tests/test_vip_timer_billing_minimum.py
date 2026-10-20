from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import services.vip_timer as vip_timer
from services.vip_timer_billing_guard import calculate_total_with_minimum


def _local_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'minimum.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE vip_timer_segments (
                order_id INTEGER NOT NULL,
                hourly_rate INTEGER NOT NULL,
                billable_seconds INTEGER NOT NULL
            )
        """))
    return engine


def test_short_order_is_billed_at_fifteen_minute_minimum(tmp_path, monkeypatch):
    engine = _local_db(tmp_path, monkeypatch)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO vip_timer_segments VALUES (1, 600, 600)")
        )

    amount, actual_seconds = calculate_total_with_minimum(1)
    assert actual_seconds == 600
    assert amount == 150


def test_short_mixed_rate_order_uses_weighted_rate_for_minimum(tmp_path, monkeypatch):
    engine = _local_db(tmp_path, monkeypatch)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vip_timer_segments VALUES (2, 300, 300)"))
        conn.execute(text("INSERT INTO vip_timer_segments VALUES (2, 600, 300)"))

    amount, actual_seconds = calculate_total_with_minimum(2)
    assert actual_seconds == 600
    # 5m@300 + 5m@600 = 75 for 10m; scale to 15m => 112.5 -> 113.
    assert amount == 113


def test_order_over_fifteen_minutes_keeps_exact_second_billing(tmp_path, monkeypatch):
    engine = _local_db(tmp_path, monkeypatch)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vip_timer_segments VALUES (3, 600, 1200)"))

    amount, actual_seconds = calculate_total_with_minimum(3)
    assert actual_seconds == 1200
    assert amount == 200
