from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer as timer
from services import vip_timer_pending_order_guard as guard


ROOT = Path(__file__).resolve().parents[1]


def _local_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-timer-pending-guard.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(timer, "SessionLocal", Local)
    db = Local()
    timer.ensure_vip_timer_tables(db)
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT
            )
            """
        )
    )
    db.commit()
    db.close()
    return Local


def _insert_timer(Local, *, order_id: int, customer_id: str, timer_status: str, order_status: str):
    db = Local()
    try:
        now = timer.utc_iso()
        db.execute(
            text(
                """
                INSERT INTO web_orders(id, status)
                VALUES (:order_id, :order_status)
                """
            ),
            {"order_id": int(order_id), "order_status": str(order_status)},
        )
        db.execute(
            text(
                """
                INSERT INTO vip_timer_sessions(
                    order_id, customer_discord_id, status,
                    current_rule_key, current_rule_label, current_category_label,
                    current_hourly_rate, final_amount, created_at, updated_at
                ) VALUES (
                    :order_id, :customer_id, :timer_status,
                    'rule', '測試玩法', '測試遊戲',
                    600, 0, :now, :now
                )
                """
            ),
            {
                "order_id": int(order_id),
                "customer_id": str(customer_id),
                "timer_status": str(timer_status),
                "now": now,
            },
        )
        db.commit()
    finally:
        db.close()


def test_pending_vip_timer_blocks_every_new_order(tmp_path, monkeypatch):
    Local = _local_db(tmp_path, monkeypatch)
    _insert_timer(
        Local,
        order_id=77,
        customer_id="1001",
        timer_status="pending_payment",
        order_status="pending_payment",
    )

    assert guard.get_pending_vip_timer_order_id("1001") == 77
    with pytest.raises(ValueError, match="一般訂單與新的 VIP 自由計時單"):
        guard.assert_customer_can_create_new_order("1001")


def test_paid_authoritative_order_reconciles_and_unblocks(tmp_path, monkeypatch):
    Local = _local_db(tmp_path, monkeypatch)
    _insert_timer(
        Local,
        order_id=88,
        customer_id="1002",
        timer_status="pending_payment",
        order_status="active",
    )

    assert guard.get_pending_vip_timer_order_id("1002") is None
    guard.assert_customer_can_create_new_order("1002")

    db = Local()
    try:
        status = db.execute(
            text("SELECT status FROM vip_timer_sessions WHERE order_id=88")
        ).scalar_one()
        assert status == "paid"
    finally:
        db.close()


def test_non_pending_timer_does_not_trigger_global_order_block(tmp_path, monkeypatch):
    Local = _local_db(tmp_path, monkeypatch)
    _insert_timer(
        Local,
        order_id=99,
        customer_id="1003",
        timer_status="paused",
        order_status="waiting_staff",
    )

    assert guard.get_pending_vip_timer_order_id("1003") is None
    guard.assert_customer_can_create_new_order("1003")


def test_discord_guard_is_outermost_after_timer_self_service_patch():
    acceptance = (ROOT / "services/vip_timer_acceptance.py").read_text(encoding="utf-8")
    guard_source = (ROOT / "services/vip_timer_pending_order_guard.py").read_text(encoding="utf-8")

    assert acceptance.index("install_vip_timer_self_service()") < acceptance.index(
        "install_discord_pending_order_guard()"
    )
    assert (
        "runtime.create_self_service_waiting_acceptance_order = guarded_create_waiting_acceptance_order"
        in guard_source
    )
    assert "dispatch.create_waiting_acceptance_order = guarded_create_waiting_acceptance_order" in guard_source


def test_website_order_service_and_vip_rules_are_wired():
    bootstrap = (ROOT / "web/app/routers/__init__.py").read_text(encoding="utf-8")
    site = (ROOT / "web/app/routers/site.py").read_text(encoding="utf-8")
    vip = (ROOT / "web/app/templates/vip.html").read_text(encoding="utf-8")

    assert "install_web_pending_order_guard()" in bootstrap
    # The public order route imports the service inside the request handler, so
    # the bootstrap patch is what every subsequent normal website checkout sees.
    assert "from web.app.services.public_order_create import (" in site
    assert "create_public_order as _create_public_order" in site
    assert "付款前不可建立任何新訂單" in vip
    assert "單次暫停最長 2 小時" in vip
    assert "跨越台灣時間的日曆日" in vip
