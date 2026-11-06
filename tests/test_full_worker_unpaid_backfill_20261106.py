from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts import repair_full_worker_unpaid_payouts_20261106 as repair
from shared.db import Base
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)


def _create_order(db, *, rule_key, pay, basis, wage, cs, paid=False, manual=False, gross=None):
    order = WebOrder(
        category="staff_internal",
        item="直接結算",
        order_rule_key=rule_key,
        status="closed",
        amount=pay,
        customer_pay_amount=pay,
        payout_base_amount=basis,
    )
    db.add(order)
    db.flush()
    db.add(OrderAssignment(
        order_id=order.id, worker_discord_id=f"worker-{order.id}", is_active=True
    ))
    payout = WorkerPayout(
        order_id=order.id,
        worker_discord_id=f"worker-{order.id}",
        gross_share=basis if gross is None else gross,
        base_rate=0.8,
        base_payout=int(wage),
        final_payout=wage,
        payout_status=PayoutStatus.PAID.value if paid else PayoutStatus.UNPAID.value,
        paid_at=datetime(2026, 11, 6) if paid else None,
    )
    db.add(payout)
    db.add(CustomerServicePayout(
        order_id=order.id,
        customer_service_discord_id=f"cs-{order.id}",
        rate=0.05,
        payout_amount=cs,
        payout_status=PayoutStatus.UNPAID.value,
    ))
    if manual:
        db.add(WorkerPayoutOverride(
            order_id=order.id,
            worker_discord_id=f"worker-{order.id}",
            manual_final_payout=wage,
        ))
    db.flush()
    return order.id


def test_dry_run_then_apply_repair_only_safe_unpaid_direct_pay_orders(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        named = _create_order(db, rule_key="staff_internal_ammo_dump_500m", pay=2650, basis=2650, wage=2200, cs=100)
        unnamed = _create_order(db, rule_key="staff_internal_ammo_dump_500m", pay=3000, basis=2650, wage=2200, cs=100)
        car = _create_order(db, rule_key="staff_internal_car_500m", pay=2480, basis=2480, wage=1984, cs=124)
        aw = _create_order(db, rule_key="staff_internal_aw_collision", pay=80, basis=80, wage=64, cs=4)
        paid = _create_order(db, rule_key="staff_internal_car_500m", pay=2480, basis=2480, wage=1984, cs=124, paid=True)
        manual = _create_order(db, rule_key="staff_internal_car_500m", pay=2480, basis=2480, wage=2111, cs=124, manual=True)
        mismatch = _create_order(db, rule_key="staff_internal_aw_collision", pay=80, basis=80, wage=60, cs=4, gross=100)
        invalid_basis = _create_order(db, rule_key="staff_internal_ammo_dump_500m", pay=3000, basis=3000, wage=2400, cs=150)
        generic = _create_order(db, rule_key="valorant_fun", pay=1000, basis=1000, wage=800, cs=50)
        db.commit()

    monkeypatch.setattr(repair, "SessionLocal", lambda: Session(engine))
    preview = repair.repair_unpaid_full_worker_payouts(apply=False)
    assert preview["counts"]["correctable"] == 4
    assert preview["counts"]["skip_paid_or_locked"] == 1
    assert preview["counts"]["skip_manual_override"] == 1
    assert preview["counts"]["skip_gross_mismatch"] == 1
    assert preview["counts"]["skip_invalid_internal_basis"] == 1
    assert len(preview["changes"]) == 4

    with Session(engine) as db:
        assert db.query(WorkerPayout).filter_by(order_id=named).one().final_payout == 2200

    applied = repair.repair_unpaid_full_worker_payouts(apply=True)
    assert applied["counts"]["fixed"] == 4
    with Session(engine) as db:
        for order_id, gross, expected_margin in [
            (named, 2650, 0),
            (unnamed, 2650, 350),
            (car, 2480, 0),
            (aw, 80, 0),
        ]:
            order = db.get(WebOrder, order_id)
            payout = db.query(WorkerPayout).filter_by(order_id=order_id).one()
            cs_row = db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
            assert payout.final_payout == gross
            assert payout.named_bonus_amount == 0
            assert payout.base_rate == 1.0
            assert cs_row.payout_amount == 0
            assert order.customer_pay_amount - payout.final_payout - cs_row.payout_amount == expected_margin
        assert db.query(WorkerPayout).filter_by(order_id=paid).one().final_payout == 1984
        assert db.query(WorkerPayout).filter_by(order_id=manual).one().final_payout == 2111
        assert db.query(WorkerPayout).filter_by(order_id=mismatch).one().final_payout == 60
        assert db.query(WorkerPayout).filter_by(order_id=invalid_basis).one().final_payout == 2400
        assert db.query(WorkerPayout).filter_by(order_id=generic).one().final_payout == 800

    again = repair.repair_unpaid_full_worker_payouts(apply=True)
    assert again["counts"].get("fixed", 0) == 0
    assert again["counts"]["already_correct"] == 4
