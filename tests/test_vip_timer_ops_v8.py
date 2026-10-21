from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer as timer
from services import vip_timer_ops as ops
from services import vip_timer_monitor as monitor


def _local_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-timer-ops.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(timer, "SessionLocal", Local)
    db = Local()
    ops.ensure_vip_timer_ops_tables(db)
    db.commit()
    return engine, Local


def _insert_session(db, *, order_id=1, customer="100", status="running"):
    now = timer.utc_iso()
    db.execute(text("""
        INSERT INTO vip_timer_sessions(
            order_id, customer_discord_id, status, current_rule_key,
            current_rule_label, current_category_label, current_hourly_rate,
            final_amount, created_at, updated_at
        ) VALUES (
            :order_id, :customer, :status, 'rule', '測試玩法', '測試遊戲',
            600, 0, :now, :now
        )
    """), {
        "order_id": int(order_id),
        "customer": str(customer),
        "status": str(status),
        "now": now,
    })


def test_vip_snapshot_stays_locked_after_order_creation(tmp_path, monkeypatch):
    _, Local = _local_db(tmp_path, monkeypatch)
    values = [("金級魔丸", 98), ("鑽石魔丸", 96)]
    monkeypatch.setattr(ops, "_current_vip_level_and_rate", lambda customer_id: values.pop(0))

    db = Local()
    try:
        _insert_session(db)
        first = ops.snapshot_vip_for_order(db, 1, "100")
        second = ops.snapshot_vip_for_order(db, 1, "100")
        db.commit()
    finally:
        db.close()

    assert first == ("金級魔丸", 98)
    assert second == ("金級魔丸", 98)
    assert values == [("鑽石魔丸", 96)]


def test_end_confirmation_requires_customer_and_staff_sides(tmp_path, monkeypatch):
    _, Local = _local_db(tmp_path, monkeypatch)
    db = Local()
    try:
        _insert_session(db, customer="100", status="running")
        db.commit()
    finally:
        db.close()

    first = ops.request_or_confirm_end(1, "100", ["200", "201"])
    repeated = ops.request_or_confirm_end(1, "100", ["200", "201"])
    confirmed = ops.request_or_confirm_end(1, "201", ["200", "201"])

    assert first["state"] == "pending"
    assert first["waiting_for"] == "staff"
    assert repeated["already_requested"] is True
    assert confirmed["confirmed"] is True
    assert confirmed["forced"] is False
    assert ops.get_end_request(1) is None


def test_support_can_force_end_confirmation_without_becoming_a_side(tmp_path, monkeypatch):
    _, Local = _local_db(tmp_path, monkeypatch)
    db = Local()
    try:
        _insert_session(db, customer="100", status="paused")
        db.commit()
    finally:
        db.close()

    result = ops.request_or_confirm_end(1, "999", ["200"])
    assert result == {"state": "confirmed", "confirmed": True, "forced": True}


def test_live_preview_keeps_whole_order_fifteen_minute_minimum():
    segments = [
        {"hourly_rate": 600, "billable_seconds": 300, "ended_at": "done"},
        {"hourly_rate": 1200, "billable_seconds": 300, "ended_at": "done"},
    ]
    gross, seconds = ops._amount_from_segments(segments, "pending_payment")
    assert seconds == 600
    # Actual mixed 10 minutes is 150T; scaled to 15 minutes becomes 225T.
    assert gross == 225


def test_ops_routes_and_live_page_are_wired_by_web_bootstrap():
    bootstrap = open("web/app/routers/__init__.py", encoding="utf-8").read()
    router = open("web/app/routers/vip_timer_ops.py", encoding="utf-8").read()
    live_js = open("web/app/static/js/pages/vip_timer_live.js", encoding="utf-8").read()

    assert "install_vip_timer_snapshot_guard()" in bootstrap
    assert "_site.router.include_router(_vip_timer_ops_router)" in bootstrap
    assert '"/admin/vip-timers"' in router
    assert '"/me/orders/{order_id}/timer/status"' in router
    assert "setInterval" in live_js


def test_runtime_installs_end_confirmation_and_monitor_after_roster_guard():
    source = open("services/vip_timer_acceptance.py", encoding="utf-8").read()
    assert "install_vip_timer_snapshot_guard()" in source
    assert "install_vip_timer_end_confirmation()" in source
    assert "install_vip_timer_monitor(bot_instance)" in source
    assert source.index("install_vip_timer_roster_runtime(") < source.index("install_vip_timer_end_confirmation()")


def test_monitor_has_long_timer_and_pending_payment_thresholds():
    assert monitor.RUNNING_THRESHOLDS[:2] == (2, 4)
    assert any(key == "pending_30m" for _, key, _ in monitor.PENDING_THRESHOLDS)
    assert any(key == "pending_24h" for _, key, _ in monitor.PENDING_THRESHOLDS)
    assert monitor.CHECK_INTERVAL_SECONDS <= 60


def test_monitor_registers_on_ready_when_configured_before_event_loop(monkeypatch):
    monkeypatch.setattr(monitor, "ensure_vip_timer_ops_tables", lambda: None)

    class DummyBot:
        def __init__(self):
            self.listeners = []

        def add_listener(self, callback, name):
            self.listeners.append((callback, name))

        def is_ready(self):
            return False

    bot = DummyBot()
    monitor.install_vip_timer_monitor(bot)

    assert bot._vip_timer_monitor_installed is True
    assert len(bot.listeners) == 1
    assert bot.listeners[0][1] == "on_ready"
