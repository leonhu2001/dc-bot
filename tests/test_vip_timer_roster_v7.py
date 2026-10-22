from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer_roster as roster
from services import vip_timer_roster_payout as payout
from shared.db import Base
from shared.models import WebOrder, WorkerPayout


def test_fixed_headcount_variants_can_resolve_adjacent_package(monkeypatch):
    rules = {
        "single": SimpleNamespace(required_staff_count=1, label="娛樂單陪"),
        "double": SimpleNamespace(required_staff_count=2, label="娛樂雙陪"),
        "triple": SimpleNamespace(required_staff_count=3, label="娛樂三陪"),
    }
    group = {
        "label": "娛樂",
        "details": [
            {"rule_key": "single", "value": "s", "vip_timer_service_type": "單陪"},
            {"rule_key": "double", "value": "d", "vip_timer_service_type": "雙陪"},
            {"rule_key": "triple", "value": "t", "vip_timer_service_type": "三陪"},
        ],
    }
    monkeypatch.setattr(roster, "ORDER_RULES", rules)
    monkeypatch.setattr(
        roster,
        "_current_gameplay_group",
        lambda rule_key, current_count: ("三角洲端遊", group),
    )

    target = roster._target_variant("single", 1, 2)
    assert target is not None
    assert target["rule_key"] == "double"
    assert target["service_type"] == "雙陪"
    assert roster._supported_counts("single", 1) == [1, 2, 3]


def test_player_count_detail_uses_selected_variant_count(monkeypatch):
    monkeypatch.setattr(
        roster,
        "ORDER_RULES",
        {
            "dynamic": SimpleNamespace(
                required_staff_count="player_count",
                min_player_count=1,
            )
        },
    )
    assert roster._detail_staff_count({"rule_key": "dynamic", "player_count": 4}) == 4


def test_scaled_integer_worker_shares_sum_to_canonical_payout_base():
    shares = payout._allocate_integer_shares(
        {"A": Decimal("1000"), "B": Decimal("500")},
        900,
    )
    assert shares == {"A": 600, "B": 300}
    assert sum(shares.values()) == 900


def test_timer_detection_fails_open_before_timer_schema_exists():
    class NoTimerSchemaDb:
        def execute(self, *args, **kwargs):
            raise RuntimeError("no such table: vip_timer_sessions")

    assert payout._is_timer_order(123, NoTimerSchemaDb()) is False


def test_segment_roster_payout_follows_actual_participation(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'timer-roster.db'}",
        connect_args={"check_same_thread": False},
    )
    Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(payout, "SessionLocal", Local)

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
                hourly_rate INTEGER NOT NULL,
                billable_seconds INTEGER NOT NULL,
                staff_ids_json TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT
            )
        """))

    db = Local()
    try:
        order = WebOrder(
            category="VIP 自由計時",
            item="自由計時｜測試",
            quantity=1,
            amount=900,
            payout_base_amount=900,
            customer_pay_amount=900,
            status="active",
            note="VIP_TIMER｜test_fixture",
        )
        db.add(order)
        db.flush()
        order_id = int(order.id)
        db.execute(text("INSERT INTO vip_timer_sessions(order_id,status) VALUES (:id,'paid')"), {"id": order_id})
        db.execute(text("""
            INSERT INTO vip_timer_segments(order_id,seq,hourly_rate,billable_seconds,staff_ids_json)
            VALUES (:id,1,1000,3600,'["A","B"]')
        """), {"id": order_id})
        db.execute(text("""
            INSERT INTO vip_timer_segments(order_id,seq,hourly_rate,billable_seconds,staff_ids_json)
            VALUES (:id,2,500,3600,'["A"]')
        """), {"id": order_id})
        db.execute(text("""
            INSERT INTO order_acceptance_claims(order_id,staff_discord_id,staff_display_name)
            VALUES (:id,'A','Alpha'),(:id,'B','Beta')
        """), {"id": order_id})
        db.commit()
    finally:
        db.close()

    assert payout.recalculate_vip_timer_worker_payouts(order_id) == 2

    db = Local()
    try:
        rows = {
            row.worker_discord_id: row
            for row in db.query(WorkerPayout).filter(WorkerPayout.order_id == order_id).all()
        }
        assert int(rows["A"].gross_share) == 600
        assert int(rows["B"].gross_share) == 300
        assert int(rows["A"].final_payout) == 480
        assert int(rows["B"].final_payout) == 240
        assert "實際參與人員" in str(rows["A"].note)
    finally:
        db.close()


def test_payout_install_preserves_order_service_recalc_signature(monkeypatch):
    from shared import order_acceptance as acceptance
    from web.app.services import order_service

    calls: list[int] = []

    def original_recalc(db, order_id: int):
        calls.append(int(order_id))

    monkeypatch.setattr(payout, "_INSTALLED", False)
    monkeypatch.setattr(order_service, "recalculate_order_payouts", original_recalc)
    monkeypatch.setattr(acceptance, "promote_acceptance_claims_to_assignments", lambda *a, **k: 0)
    monkeypatch.setattr(payout, "_is_timer_order", lambda order_id, db: False)

    class DummyDb:
        def get(self, model, order_id):
            return None

    payout.install_vip_timer_roster_payout()
    order_service.recalculate_order_payouts(DummyDb(), 123)
    assert calls == [123]


def test_roster_runtime_has_persistent_adjust_button_and_fast_ack_source():
    source = open("services/vip_timer_roster_runtime.py", encoding="utf-8").read()
    assert 'custom_id="vip_timer:roster"' in source
    assert "await interaction.response.defer()" in source
    assert source.index("await interaction.response.defer()") < source.index("result = adjust_roster(")


def test_roster_changes_close_old_segment_and_switch_pending_rule_source():
    source = open("services/vip_timer_roster.py", encoding="utf-8").read()
    assert "ended_at=:now" in source
    assert "current_hourly_rate=0" in source
    assert "resume_after_roster_change" in source
    assert "target_rule_key" in source
    assert "_target_variant" in source


def test_web_process_installs_timer_roster_payout_guard():
    source = open("web/app/routers/__init__.py", encoding="utf-8").read()
    assert "install_vip_timer_roster_payout" in source
    assert "install_vip_timer_roster_payout()" in source
