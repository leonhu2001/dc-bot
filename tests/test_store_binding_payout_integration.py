from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.db import Base, ensure_store_binding_constraints
from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout
from shared.staff_models import StaffStoreBinding
from web.app.services import worker_bonus_payout


TAIPEI = timezone(timedelta(hours=8))


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE order_reports (id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT)"))
        conn.execute(text("CREATE TABLE order_report_workers (id INTEGER PRIMARY KEY, report_id INTEGER, worker_discord_id TEXT, streamed INTEGER)"))
    return engine


def _new_order(*, closed_at: datetime, amount: int = 1000) -> WebOrder:
    return WebOrder(
        category="測試",
        item="綁店整合測試",
        quantity=1,
        amount=amount,
        payout_base_amount=amount,
        customer_pay_amount=amount,
        status="closed",
        closed_at=closed_at,
    )


def test_report_approval_applies_store_binding_and_recalculates_cs(monkeypatch):
    engine = _engine()
    close_at = datetime(2026, 10, 10, 12, 0, 0)
    worker_id = "worker-90"

    with Session(engine) as db:
        previous_order = _new_order(closed_at=datetime(2026, 9, 15, 12, 0, 0), amount=6250)
        current_order = _new_order(closed_at=close_at)
        db.add_all([previous_order, current_order])
        db.flush()

        db.add(
            WorkerPayout(
                order_id=previous_order.id,
                worker_discord_id=worker_id,
                gross_share=6250,
                base_rate=0.8,
                base_payout=5000,
                final_payout=5000,
                payout_status=PayoutStatus.PAID.value,
                paid_at=datetime(2026, 9, 15, 12, 30, 0),
            )
        )
        payout = WorkerPayout(
            order_id=current_order.id,
            worker_discord_id=worker_id,
            gross_share=1000,
            base_rate=0.8,
            base_payout=800,
            final_payout=800,
            has_named_bonus=True,
            payout_status=PayoutStatus.UNPAID.value,
        )
        cs = CustomerServicePayout(
            order_id=current_order.id,
            customer_service_discord_id="cs-1",
            rate=0.05,
            payout_amount=50,
            payout_status=PayoutStatus.UNPAID.value,
        )
        binding = StaffStoreBinding(
            staff_discord_id=worker_id,
            status="active",
            started_at=close_at - timedelta(days=2),
        )
        db.add_all([payout, cs, binding])
        db.flush()
        db.execute(
            text("INSERT INTO order_reports (id, order_id, status) VALUES (1, :order_id, 'approved')"),
            {"order_id": current_order.id},
        )
        db.execute(
            text("INSERT INTO order_report_workers (id, report_id, worker_discord_id, streamed) VALUES (1, 1, :worker_id, 1)"),
            {"worker_id": worker_id},
        )
        current_order_id = current_order.id
        payout_id = payout.id
        cs_id = cs.id
        db.commit()

    monkeypatch.setattr(worker_bonus_payout, "SessionLocal", lambda: Session(engine))
    result = worker_bonus_payout.apply_approved_report_worker_bonuses(
        current_order_id,
        now=datetime(2026, 10, 20, 12, 0, 0, tzinfo=TAIPEI),
    )

    assert result["workers"][0]["rate"] == pytest.approx(0.90)
    assert result["workers"][0]["previous_month_paid_salary"] == 5000
    assert result["workers"][0]["store_bound_at_close"] is True

    with Session(engine) as db:
        payout = db.get(WorkerPayout, payout_id)
        cs = db.get(CustomerServicePayout, cs_id)
        assert payout.final_payout == 900
        assert "綁店3%" in str(payout.note)
        assert cs.payout_amount == 25
        assert cs.rate == pytest.approx(0.025)


def test_paid_and_manual_worker_payouts_are_not_rewritten(monkeypatch):
    engine = _engine()
    close_at = datetime(2026, 10, 10, 12, 0, 0)

    with Session(engine) as db:
        order = _new_order(closed_at=close_at, amount=2000)
        db.add(order)
        db.flush()
        paid = WorkerPayout(
            order_id=order.id,
            worker_discord_id="paid-worker",
            gross_share=1000,
            final_payout=777,
            payout_status=PayoutStatus.PAID.value,
            paid_at=close_at + timedelta(days=1),
        )
        manual = WorkerPayout(
            order_id=order.id,
            worker_discord_id="manual-worker",
            gross_share=1000,
            final_payout=666,
            payout_status=PayoutStatus.UNPAID.value,
            note="手動指定分潤：特殊拆分",
        )
        db.add_all([paid, manual])
        db.flush()
        db.execute(
            text("INSERT INTO order_reports (id, order_id, status) VALUES (1, :order_id, 'approved')"),
            {"order_id": order.id},
        )
        order_id = order.id
        paid_id = paid.id
        manual_id = manual.id
        db.commit()

    monkeypatch.setattr(worker_bonus_payout, "SessionLocal", lambda: Session(engine))
    worker_bonus_payout.apply_approved_report_worker_bonuses(order_id)

    with Session(engine) as db:
        assert db.get(WorkerPayout, paid_id).final_payout == 777
        assert db.get(WorkerPayout, manual_id).final_payout == 666


def test_store_binding_constraint_repairs_duplicates_and_blocks_new_duplicate():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    StaffStoreBinding.__table__.create(engine)
    first_start = datetime(2026, 10, 1, 0, 0, 0)
    second_start = datetime(2026, 10, 5, 0, 0, 0)

    with Session(engine) as db:
        db.add_all(
            [
                StaffStoreBinding(staff_discord_id="duplicate", status="active", started_at=first_start),
                StaffStoreBinding(staff_discord_id="duplicate", status="active", started_at=second_start),
            ]
        )
        db.commit()

    ensure_store_binding_constraints(engine)

    with Session(engine) as db:
        rows = list(
            db.scalars(
                select(StaffStoreBinding)
                .where(StaffStoreBinding.staff_discord_id == "duplicate")
                .order_by(StaffStoreBinding.started_at.asc())
            ).all()
        )
        assert [row.status for row in rows] == ["ended", "active"]
        assert rows[0].ended_at == second_start
        assert "重複綁店資格" in str(rows[0].note)

        db.add(StaffStoreBinding(staff_discord_id="duplicate", status="active", started_at=second_start + timedelta(days=1)))
        with pytest.raises(IntegrityError):
            db.commit()
