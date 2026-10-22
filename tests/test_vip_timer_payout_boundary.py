from __future__ import annotations

from types import SimpleNamespace

from services import vip_timer_roster_payout
from shared import order_acceptance
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
