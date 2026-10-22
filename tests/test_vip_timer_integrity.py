from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import self_service_selection_state as selection
from services import vip_timer_integrity as integrity
from shared import web_order_sync
from shared.db import Base
from shared.models import WebOrder


def _db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-timer-integrity.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE vip_timer_sessions (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                status TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE vip_timer_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                billable_seconds INTEGER NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE vip_timer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                action TEXT
            )
        """))
        for table in (
            "vip_timer_end_requests",
            "vip_timer_corrections",
            "vip_timer_disputes",
            "vip_timer_alerts",
        ):
            conn.execute(text(f"""
                CREATE TABLE {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL
                )
            """))

    monkeypatch.setattr(integrity, "SessionLocal", Local)
    monkeypatch.setattr(web_order_sync, "SessionLocal", Local)
    return engine, Local


def _add_order(
    Local,
    *,
    order_id: int,
    category: str,
    item: str,
    note: str | None = None,
    price_snapshot: dict | None = None,
    ticket_channel_id: str | None = None,
):
    db = Local()
    try:
        order = WebOrder(
            id=int(order_id),
            ticket_channel_id=ticket_channel_id,
            category=category,
            item=item,
            quantity=1,
            amount=1000,
            status="closed",
            note=note,
            price_snapshot_json=(
                json.dumps(price_snapshot, ensure_ascii=False)
                if price_snapshot is not None
                else None
            ),
        )
        db.add(order)
        db.flush()
        db.execute(
            text(
                "INSERT INTO vip_timer_sessions(order_id,customer_discord_id,status) "
                "VALUES (:id,'customer','paid')"
            ),
            {"id": int(order_id)},
        )
        db.execute(
            text("INSERT INTO vip_timer_segments(order_id,billable_seconds) VALUES (:id,3600)"),
            {"id": int(order_id)},
        )
        db.execute(
            text("INSERT INTO vip_timer_events(order_id,action) VALUES (:id,'created')"),
            {"id": int(order_id)},
        )
        for table in (
            "vip_timer_end_requests",
            "vip_timer_corrections",
            "vip_timer_disputes",
            "vip_timer_alerts",
        ):
            db.execute(
                text(f"INSERT INTO {table}(order_id) VALUES (:id)"),
                {"id": int(order_id)},
            )
        db.commit()
    finally:
        db.close()


def _timer_row_count(Local, table: str, order_id: int) -> int:
    db = Local()
    try:
        return int(
            db.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE order_id=:id"),
                {"id": int(order_id)},
            ).scalar_one()
        )
    finally:
        db.close()


def test_web_order_266_sweet_double_is_not_a_timer_and_stale_rows_are_removed(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=266,
        category="通用單",
        item="甜蜜雙陪",
    )

    db = Local()
    try:
        assert integrity.is_canonical_vip_timer_order(266, db) is False
        assert integrity.cleanup_stale_vip_timer_rows(db) == [266]
        db.commit()
    finally:
        db.close()

    for table in (
        "vip_timer_end_requests",
        "vip_timer_corrections",
        "vip_timer_disputes",
        "vip_timer_alerts",
        "vip_timer_events",
        "vip_timer_segments",
        "vip_timer_sessions",
    ):
        assert _timer_row_count(Local, table, 266) == 0


def test_discord_vip_timer_identity_is_preserved(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=10,
        category="VIP 自由計時",
        item="自由計時｜甜蜜雙陪",
        note="VIP_TIMER｜initial_rule=basic_sweet_double_any｜先玩後付",
    )

    db = Local()
    try:
        assert integrity.is_canonical_vip_timer_order(10, db) is True
        assert integrity.cleanup_stale_vip_timer_rows(db) == []
        db.commit()
    finally:
        db.close()

    assert _timer_row_count(Local, "vip_timer_sessions", 10) == 1


def test_web_vip_timer_identity_is_preserved_with_source_category(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=11,
        category="通用單",
        item="自由計時｜雙陪(不限)",
        note="VIP_TIMER｜initial_rule=basic_sweet_double_any｜先玩後付",
        price_snapshot={"vip_timer": True, "initial_rule_key": "basic_sweet_double_any"},
    )

    db = Local()
    try:
        assert integrity.is_canonical_vip_timer_order(11, db) is True
        assert integrity.cleanup_stale_vip_timer_rows(db) == []
        db.commit()
    finally:
        db.close()


def test_marker_only_on_repurposed_normal_order_is_not_timer(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=12,
        category="通用單",
        item="甜蜜雙陪",
        note="VIP_TIMER｜舊資料殘留",
        price_snapshot={"customer_pay_amount": 1000},
    )

    db = Local()
    try:
        assert integrity.is_canonical_vip_timer_order(12, db) is False
        assert integrity.cleanup_stale_vip_timer_rows(db) == [12]
        db.commit()
    finally:
        db.close()


def test_structural_only_legacy_timer_fails_closed_without_deleting_evidence(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=13,
        category="VIP 自由計時",
        item="自由計時｜歷史玩法",
        note=None,
    )

    db = Local()
    try:
        assert integrity.is_canonical_vip_timer_order(13, db) is False
        assert integrity.cleanup_stale_vip_timer_rows(db) == []
        db.commit()
    finally:
        db.close()

    assert _timer_row_count(Local, "vip_timer_sessions", 13) == 1


def test_web_order_delete_also_removes_vip_timer_metadata(tmp_path, monkeypatch):
    _, Local = _db(tmp_path, monkeypatch)
    _add_order(
        Local,
        order_id=20,
        ticket_channel_id="ticket-20",
        category="VIP 自由計時",
        item="自由計時｜甜蜜雙陪",
        note="VIP_TIMER｜initial_rule=basic_sweet_double_any｜先玩後付",
    )

    from services import loyalty_benefits, vip_monthly_benefits

    monkeypatch.setattr(loyalty_benefits, "release_coupon_for_order", lambda order_id: None)
    monkeypatch.setattr(
        vip_monthly_benefits,
        "release_cash_benefits_for_channel",
        lambda ticket_channel_id: None,
    )

    assert web_order_sync.delete_web_order_by_ticket_channel(
        ticket_channel_id="ticket-20"
    ) is True

    db = Local()
    try:
        assert db.get(WebOrder, 20) is None
    finally:
        db.close()
    assert _timer_row_count(Local, "vip_timer_sessions", 20) == 0


def test_product_change_clears_stale_vip_timer_draft_flags():
    data = {
        "vip_timer_order": True,
        "vip_timer_source_category": "general",
        "amount": 0,
        "payment_method": "待付款",
    }

    selection.clear_product_dependent_selection_state(data)

    assert "vip_timer_order" not in data
    assert "vip_timer_source_category" not in data
