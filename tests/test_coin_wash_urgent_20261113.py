from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.coin_wash_urgent_policy import (
    EXTERNAL_URGENT_FEE,
    INTERNAL_URGENT_FEE,
    apply_urgent_fee,
    selected_urgent_fee,
    urgent_fee_for_rule,
    urgent_fee_from_price_snapshot,
)
from services.one_companion_one_guard_payout import calculate_one_companion_one_guard_order_payout
from services.staff_internal_ammo_dump_policy import calculate_internal_ammo_dump_financials


@pytest.mark.parametrize(
    ("rule_key", "expected"),
    [
        ("staff_internal_car_500m", 260),
        ("staff_internal_ammo_dump_500m", 260),
        ("farm_halfcoin_120m", 280),
        ("farm_halfcoin_360m", 280),
        ("staff_internal_aw_collision", 0),
        ("farm_aw_collision_1_100", 0),
        ("steam_play", 0),
    ],
)
def test_urgent_rule_allowlist(rule_key, expected):
    assert urgent_fee_for_rule(rule_key) == expected
    assert selected_urgent_fee(rule_key, {"coin_wash_urgent": True}) == expected
    assert selected_urgent_fee(rule_key, {"coin_wash_urgent": False}) == 0


@pytest.mark.parametrize(
    ("named", "customer_base", "margin", "customer_service"),
    [(True, 2650, 0, 0), (False, 3000, 350, 88)],
)
def test_internal_named_unnamed_urgency_preserves_store_and_cs(
    named, customer_base, margin, customer_service
):
    quote = SimpleNamespace(base_amount=2650, staff_adjustment_amount=0, service_quantity=1)
    data = {"staff_internal_ammo_named": named, "coin_wash_urgent": True}
    base = calculate_internal_ammo_dump_financials(quote, data)
    result = apply_urgent_fee("staff_internal_ammo_dump_500m", data, base)

    assert result["customer_pay_amount"] == customer_base + INTERNAL_URGENT_FEE
    assert result["payout_base_amount"] == 2650
    assert result["store_margin_amount"] == margin
    assert result["customer_service_payout_amount"] == customer_service
    assert result["urgent_fee_amount"] == 260

    direct = calculate_one_companion_one_guard_order_payout(
        rule_key="staff_internal_ammo_dump_500m",
        total_amount=result["payout_base_amount"],
        customer_service_total_amount=result["customer_pay_amount"] - result["urgent_fee_amount"],
        worker_roles=[("worker-1", "booster")],
    )
    assert direct is not None
    assert direct.worker_payouts[0].final_payout + INTERNAL_URGENT_FEE == 2910
    assert direct.customer_service_payout == customer_service
    assert (
        result["customer_pay_amount"]
        - (direct.total_worker_payout + INTERNAL_URGENT_FEE)
        - direct.customer_service_payout
    ) == margin - customer_service


def test_public_washing_urgency_is_only_surcharge_not_commission_base():
    base = {
        "rule_original_amount": 1250, "service_original_amount": 1250,
        "original_amount": 1250, "priced_amount": 1250,
        "customer_pay_amount": 1250, "payout_base_amount": 1250,
    }
    with_urgent = apply_urgent_fee("farm_halfcoin_120m", {"coin_wash_urgent": True}, base)
    assert with_urgent["customer_pay_amount"] == 1250 + EXTERNAL_URGENT_FEE
    assert with_urgent["payout_base_amount"] == 1250
    assert base["customer_pay_amount"] == 1250


def test_payroll_bonus_only_from_matching_snapshot():
    good = {"order_rule_key": "staff_internal_car_500m", "urgent_fee_amount": 260}
    assert urgent_fee_from_price_snapshot(json.dumps(good)) == 260
    assert urgent_fee_from_price_snapshot({**good, "urgent_fee_amount": 2600}) == 0
    assert urgent_fee_from_price_snapshot({"order_rule_key": "steam_play", "urgent_fee_amount": 260}) == 0
    assert urgent_fee_from_price_snapshot("not-json") == 0


@pytest.mark.parametrize(
    ("rule_key", "paid", "basis", "fee", "cs_expected"),
    [
        ("staff_internal_ammo_dump_500m", 3260, 2650, 260, 88),
        ("staff_internal_ammo_dump_500m", 2910, 2650, 260, 0),
        ("staff_internal_car_500m", 2740, 2480, 260, 0),
        ("farm_halfcoin_120m", 1530, 1250, 280, 0),
    ],
)
def test_web_salary_recalculation_and_report_preserve_entire_urgent_fee(
    monkeypatch, rule_key, paid, basis, fee, cs_expected
):
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from shared.db import Base
    from shared.models import (
        CustomerServicePayout, OrderAssignment, PayoutStatus, WebOrder, WorkerPayout,
    )
    from web.app.services import worker_bonus_payout as report_bonus
    from web.app.services.order_service import recalculate_order_payouts

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        order = WebOrder(
            category="staff_internal" if rule_key.startswith("staff_internal") else "farm",
            item="洗幣加急",
            order_rule_key=rule_key,
            amount=paid,
            customer_pay_amount=paid,
            payout_base_amount=basis,
            price_snapshot_json=json.dumps({
                "order_rule_key": rule_key,
                "urgent_fee_amount": fee,
            }),
            status="closed",
            closed_at=datetime(2026, 11, 13, 0, 0, 0),
        )
        db.add(order)
        db.flush()
        db.add(OrderAssignment(
            order_id=order.id,
            worker_discord_id="worker-1",
            is_active=True,
            role_type="booster",
        ))
        db.flush()
        recalculate_order_payouts(db, int(order.id))
        db.commit()
        order_id = int(order.id)

    with Session(engine) as db:
        wage = db.query(WorkerPayout).filter_by(order_id=order_id).one()
        cs = db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
        assert wage.final_payout == basis + fee
        assert cs.payout_amount == cs_expected
        assert paid - wage.final_payout - cs.payout_amount == (
            262 if cs_expected == 88 else 0
        )
        assert "加急" in wage.note

    monkeypatch.setattr(report_bonus, "SessionLocal", lambda: Session(engine))
    report_bonus.apply_approved_report_worker_bonuses(order_id)

    with Session(engine) as db:
        wage = db.query(WorkerPayout).filter_by(order_id=order_id).one()
        cs = db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
        assert wage.payout_status == PayoutStatus.UNPAID.value
        assert wage.final_payout == basis + fee
        assert cs.payout_amount == cs_expected
        assert "加急" in wage.note
