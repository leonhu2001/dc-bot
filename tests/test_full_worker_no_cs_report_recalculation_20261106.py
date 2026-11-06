from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
)
from web.app.services import worker_bonus_payout as bonuses
from web.app.services.order_service import get_worker_dispatch_payout_preview


@pytest.mark.parametrize(
    ("rule_key", "customer_pay", "worker_base", "expected_store"),
    [
        ("staff_internal_ammo_dump_500m", 2650, 2650, 0),
        ("staff_internal_ammo_dump_500m", 3000, 2650, 350),
        ("staff_internal_car_500m", 2480, 2480, 0),
        ("staff_internal_aw_collision", 52, 52, 0),  # 13 AW rounds at 4T
        ("farm_halfcoin_120m", 1800, 1800, 0),
        ("farm_aw_collision_501_plus", 400, 400, 0),
    ],
)
def test_approved_report_never_reapplies_generic_wage_or_cs_commission(
    monkeypatch, rule_key, customer_pay, worker_base, expected_store
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        order = WebOrder(
            category="staff_internal" if rule_key.startswith("staff_internal") else "farm",
            item="直接結算代肝",
            order_rule_key=rule_key,
            amount=customer_pay,
            customer_pay_amount=customer_pay,
            payout_base_amount=worker_base,
            status="closed",
            closed_at=datetime(2026, 11, 6, 0, 0, 0),
        )
        db.add(order)
        db.flush()
        db.add_all([
            OrderAssignment(
                order_id=order.id,
                worker_discord_id="worker-1",
                has_named_bonus=True,  # must never increase direct-pay payout
                is_active=True,
            ),
            WorkerPayout(
                order_id=order.id,
                worker_discord_id="worker-1",
                gross_share=worker_base,
                base_rate=0.8,
                base_payout=int(worker_base * 0.8),
                named_bonus_rate=0.03,
                named_bonus_amount=0,
                final_payout=int(worker_base * 0.8),
                has_named_bonus=True,
                payout_status=PayoutStatus.UNPAID.value,
                note="分潤：基礎80%（舊錯誤）",
            ),
            CustomerServicePayout(
                order_id=order.id,
                customer_service_discord_id="cs-1",
                rate=0.05,
                payout_amount=int(worker_base * 0.05),
                payout_status=PayoutStatus.UNPAID.value,
            ),
        ])
        db.commit()
        order_id = order.id

    monkeypatch.setattr(bonuses, "SessionLocal", lambda: Session(engine))

    def forbidden(*args, **kwargs):
        raise AssertionError("full-payout direct orders must not calculate optional bonuses")

    monkeypatch.setattr(bonuses, "previous_month_performance", forbidden)
    monkeypatch.setattr(bonuses, "is_store_binding_effective_at", forbidden)
    monkeypatch.setattr(bonuses, "_approved_stream_map", forbidden)
    monkeypatch.setattr(bonuses, "_assignment_stream_override_map", forbidden)

    result = bonuses.apply_approved_report_worker_bonuses(order_id)

    with Session(engine) as db:
        payout = db.query(WorkerPayout).filter_by(order_id=order_id).one()
        cs = db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
        assert payout.base_rate == pytest.approx(1.0)
        assert payout.base_payout == worker_base
        assert payout.final_payout == worker_base
        assert payout.named_bonus_amount == 0
        assert payout.named_bonus_rate == 0
        assert "全額 100%" in payout.note
        assert cs.rate == 0
        assert cs.payout_amount == 0
        assert customer_pay - payout.final_payout - cs.payout_amount == expected_store

    assert result["workers"][0]["rate"] == 1.0
    assert result["workers"][0]["previous_month_bonus"] is False
    assert result["workers"][0]["store_bound_at_close"] is False


def test_special_payout_paid_entries_are_not_silently_rewritten(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        order = WebOrder(
            category="staff_internal",
            item="已發薪歷史紀錄",
            order_rule_key="staff_internal_car_500m",
            status="closed",
            amount=2480,
            payout_base_amount=2480,
        )
        db.add(order)
        db.flush()
        db.add_all([
            WorkerPayout(
                order_id=order.id,
                worker_discord_id="worker-1",
                gross_share=2480,
                final_payout=2000,
                payout_status=PayoutStatus.PAID.value,
                paid_at=datetime(2026, 11, 6),
            ),
            CustomerServicePayout(
                order_id=order.id,
                customer_service_discord_id="cs-1",
                payout_amount=100,
                payout_status=PayoutStatus.PAID.value,
                paid_at=datetime(2026, 11, 6),
            ),
        ])
        db.commit()
        order_id = order.id

    monkeypatch.setattr(bonuses, "SessionLocal", lambda: Session(engine))
    bonuses.apply_approved_report_worker_bonuses(order_id)
    with Session(engine) as db:
        assert db.query(WorkerPayout).filter_by(order_id=order_id).one().final_payout == 2000
        assert db.query(CustomerServicePayout).filter_by(order_id=order_id).one().payout_amount == 100


@pytest.mark.parametrize(
    ("key", "basis"),
    [
        ("staff_internal_ammo_dump_500m", 2650),
        ("staff_internal_car_500m", 2480),
        ("staff_internal_aw_collision", 52),
    ],
)
def test_dispatch_website_shows_full_worker_preview(key, basis):
    order = SimpleNamespace(
        status="waiting_acceptance",
        order_rule_key=key,
        payouts=[],
        payout_base_amount=basis,
        dispatch_required_staff_count=1,
    )
    preview = get_worker_dispatch_payout_preview(order, "worker-1")
    assert preview["is_estimate"] is True
    assert preview["amount"] == basis
