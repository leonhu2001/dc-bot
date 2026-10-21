from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer as timer
from services import vip_timer_monitor as monitor
from services import vip_timer_ops as ops
from services.vip_timer_pause_expiry import (
    PAUSE_MAX_SECONDS,
    PAUSE_WARNING_SECONDS,
    pause_state,
)


def _fixed(year=2026, month=10, day=21, hour=8, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_pause_state_warns_at_one_hour_and_expires_at_two_hours():
    now = _fixed()
    warning = pause_state(
        {"status": "paused", "paused_at": timer.utc_iso(now - timedelta(seconds=PAUSE_WARNING_SECONDS))},
        now=now,
    )
    assert warning["warning"] is True
    assert warning["expired"] is False

    expired = pause_state(
        {"status": "paused", "paused_at": timer.utc_iso(now - timedelta(seconds=PAUSE_MAX_SECONDS))},
        now=now,
    )
    assert expired["expired"] is True
    assert expired["reason"] == "timeout"


def test_pause_state_blocks_cross_day_even_before_two_hours():
    # Taiwan: 2026-10-20 23:50 -> 2026-10-21 00:10, only 20 minutes elapsed.
    paused = datetime(2026, 10, 20, 15, 50, tzinfo=timezone.utc)
    now = datetime(2026, 10, 20, 16, 10, tzinfo=timezone.utc)
    state = pause_state(
        {"status": "paused", "paused_at": timer.utc_iso(paused)},
        now=now,
    )
    assert state["age_seconds"] == 20 * 60
    assert state["expired"] is True
    assert state["crossed_day"] is True
    assert state["reason"] == "cross_day"


def _local_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-pause-expiry.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(timer, "SessionLocal", Local)
    db = Local()
    ops.ensure_vip_timer_ops_tables(db)
    db.commit()
    return Local


def _insert_paused(Local, *, now: datetime, paused_at: datetime, order_id=1):
    db = Local()
    try:
        db.execute(text("""
            INSERT INTO vip_timer_sessions(
                order_id, customer_discord_id, ticket_channel_id, status,
                current_rule_key, current_rule_label, current_category_label,
                current_hourly_rate, paused_at, final_amount, created_at, updated_at
            ) VALUES (
                :order_id, '100', '999', 'paused', 'rule', '玩法', '遊戲',
                600, :paused_at, 0, :now, :now
            )
        """), {
            "order_id": int(order_id),
            "paused_at": timer.utc_iso(paused_at),
            "now": timer.utc_iso(now),
        })
        db.commit()
    finally:
        db.close()


def test_monitor_emits_pause_warning_and_expiry(tmp_path, monkeypatch):
    now = _fixed()
    Local = _local_db(tmp_path, monkeypatch)
    monkeypatch.setattr(timer, "utc_now", lambda: now)

    _insert_paused(Local, now=now, paused_at=now - timedelta(minutes=61), order_id=1)
    due = monitor._due_alerts()
    assert any(item["alert_key"] == "pause_1h" for item in due)

    db = Local()
    try:
        db.execute(text("DELETE FROM vip_timer_sessions WHERE order_id=1"))
        db.commit()
    finally:
        db.close()

    _insert_paused(Local, now=now, paused_at=now - timedelta(hours=2, minutes=1), order_id=2)
    due = monitor._due_alerts()
    assert any(item["alert_key"] == "pause_expired_2h" for item in due)


def test_runtime_installs_pause_expiry_as_outer_resume_guard():
    source = open("services/vip_timer_acceptance.py", encoding="utf-8").read()
    assert "install_vip_timer_pause_expiry()" in source
    assert source.index("install_vip_timer_end_confirmation()") < source.index("install_vip_timer_pause_expiry()")
    assert source.index("install_vip_timer_pause_expiry()") < source.index("install_vip_timer_monitor(bot_instance)")


def test_monitor_includes_paused_sessions():
    source = open("services/vip_timer_monitor.py", encoding="utf-8").read()
    assert "('running','paused','pending_payment')" in source
    assert "pause_expired_cross_day" in source
    assert "pause_expired_2h" in source
