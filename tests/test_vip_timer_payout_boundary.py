from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer, vip_timer_roster, vip_timer_roster_payout, vip_timer_runtime_guard
from shared import order_acceptance
from shared.db import Base
from web.app.services import order_service


class _FakeDb:
    def __init__(self, events: list[str]):
        self.events = events

    def flush(self) -> None:
        self.events.append("flush")

    def get(self, model, order_id: int):
        self.events.append("get")
        return SimpleNamespace(id=int(order_id))


def test_timer_recalculation_flushes_generic_rows_before_ledger_rewrite(monkeypatch):
    events: list[str] = []
    original_recalculate = order_service.recalculate_order_payouts
    original_promote = order_acceptance.promote_acceptance_claims_to_assignments

    def fake_recalculate(db, order_id: int):
        events.append("generic")
        return "generic-result"

    def fake_promote(*args, **kwargs):
        return 1

    def fake_rewrite(db, order):
        events.append("timer-rewrite")
        return 2

    monkeypatch.setattr(order_service, "recalculate_order_payouts", fake_recalculate)
    monkeypatch.setattr(order_acceptance, "promote_acceptance_claims_to_assignments", fake_promote)
    monkeypatch.setattr(vip_timer_roster_payout, "_is_timer_order", lambda order_id, db: True)
    monkeypatch.setattr(vip_timer_roster_payout, "_rewrite_worker_payouts", fake_rewrite)
    vip_timer_roster_payout._INSTALLED = False

    try:
        vip_timer_roster_payout.install_vip_timer_roster_payout()
        result = order_service.recalculate_order_payouts(_FakeDb(events), 270)

        assert result == "generic-result"
        assert events == [
            "generic",
            "flush",
            "get",
            "timer-rewrite",
            "flush",
        ]
    finally:
        order_service.recalculate_order_payouts = original_recalculate
        order_acceptance.promote_acceptance_claims_to_assignments = original_promote
        vip_timer_roster_payout._INSTALLED = False


def test_payment_promotion_does_not_launch_second_timer_recalculation(monkeypatch):
    promoted_calls: list[int] = []
    second_recalculate_calls: list[int] = []
    original_recalculate = order_service.recalculate_order_payouts
    original_promote = order_acceptance.promote_acceptance_claims_to_assignments

    def fake_recalculate(db, order_id: int):
        return None

    def fake_promote(*args, **kwargs):
        order_id = kwargs.get("order_id")
        if order_id is None and args:
            order_id = args[0]
        promoted_calls.append(int(order_id))
        return 2

    monkeypatch.setattr(order_service, "recalculate_order_payouts", fake_recalculate)
    monkeypatch.setattr(order_acceptance, "promote_acceptance_claims_to_assignments", fake_promote)
    monkeypatch.setattr(
        vip_timer_roster_payout,
        "recalculate_vip_timer_worker_payouts",
        lambda order_id: second_recalculate_calls.append(int(order_id)),
    )
    vip_timer_roster_payout._INSTALLED = False

    try:
        vip_timer_roster_payout.install_vip_timer_roster_payout()
        result = order_acceptance.promote_acceptance_claims_to_assignments(order_id=270)

        assert result == 2
        assert promoted_calls == [270]
        assert second_recalculate_calls == []
    finally:
        order_service.recalculate_order_payouts = original_recalculate
        order_acceptance.promote_acceptance_claims_to_assignments = original_promote
        vip_timer_roster_payout._INSTALLED = False


def test_topsecret_timer_payout_keeps_the_basis_of_each_segment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'timer-payout.db'}")
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    for module in (vip_timer, vip_timer_roster, vip_timer_runtime_guard):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(
        vip_timer_roster, "get_acceptance_state", lambda order_id: SimpleNamespace(is_full=True),
    )
    monkeypatch.setattr(
        vip_timer_roster_payout, "_staff_role_types",
        lambda order_id, db: {"guard": "booster", "companion": "companion"},
    )
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(vip_timer, "utc_now", lambda: now)
    order_id = 270
    rule_key = "basic_one_companion_one_guard_topsecret"
    staff_ids = ["guard", "companion"]

    def worker_payouts(amount):
        with sessions() as db:
            plan = vip_timer_roster_payout._worker_payout_plan(
                db, SimpleNamespace(id=order_id, payout_base_amount=amount),
            )
        return {
            worker: (payout["gross_share"], payout["final_payout"])
            for worker, payout in plan.items()
        }

    with sessions.begin() as db:
        vip_timer.create_vip_timer_session(
            db, order_id=order_id, customer_id="customer", initial_rule_key=rule_key,
        )
    vip_timer.start_timer(order_id, "guard", staff_ids)
    now += timedelta(hours=1)
    vip_timer.pause_timer(order_id, "guard")
    assert vip_timer.list_segments(order_id)[0]["topsecret_companion_basis"] == 400
    assert worker_payouts(900) == {"guard": (500, 400), "companion": (400, 320)}

    # Simulate the same 900T segment written by the prior schema before migration.
    with sessions.begin() as db:
        db.execute(text("ALTER TABLE vip_timer_segments DROP COLUMN topsecret_companion_basis"))
    assert worker_payouts(900) == {"guard": (500, 400), "companion": (350, 280)}

    vip_timer.switch_rule(order_id, rule_key, "guard", staff_ids)
    vip_timer.resume_timer(order_id, "guard")
    now += timedelta(hours=1)
    with sessions.begin() as db:
        vip_timer_roster._close_live_segment(db, order_id, "running", now)

    vip_timer_runtime_guard._ensure_segment_snapshot_columns()
    vip_timer_roster.resume_with_new_roster_segment(
        order_id, actor_id="guard", pricing_snapshot=vip_timer.rule_snapshot(rule_key),
        staff_ids=staff_ids,
    )
    now += timedelta(hours=1)
    vip_timer.pause_timer(order_id, "guard")

    assert [
        (segment["hourly_rate"], segment["topsecret_companion_basis"])
        for segment in vip_timer.list_segments(order_id)
    ] == [(900, None), (900, 400), (900, 400)]
    assert worker_payouts(2700) == {"guard": (1500, 1200), "companion": (1150, 920)}
