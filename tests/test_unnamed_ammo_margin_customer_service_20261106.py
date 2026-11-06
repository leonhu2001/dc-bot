from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
)
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RULE_KEY,
    NAMED_PRICE,
    UNNAMED_PRICE,
    WORKER_PAYOUT,
    UNNAMED_CS_PAYOUT,
    UNNAMED_STORE_RETAINED,
    calculate_internal_ammo_dump_cs_payout,
)
from shared.db import Base
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    WebOrder,
    WorkerPayout,
)
from web.app.services.order_service import recalculate_order_payouts
from web.app.services.accounting_reconciliation_policy import (
    _policy_consistency_for_order,
)


def test_unnamed_margin_rounds_to_integer_T_without_charging_worker():
    assert UNNAMED_PRICE - NAMED_PRICE == 350
    assert WORKER_PAYOUT == 2650
    assert UNNAMED_CS_PAYOUT == 88
    assert UNNAMED_STORE_RETAINED == 262
    assert calculate_internal_ammo_dump_cs_payout(AMMO_DUMP_RULE_KEY, 3000, 2650) == 88
    assert calculate_internal_ammo_dump_cs_payout(AMMO_DUMP_RULE_KEY, 2650, 2650) == 0
    assert calculate_internal_ammo_dump_cs_payout(AMMO_DUMP_RULE_KEY, 3000, 3000) == 0
    assert calculate_internal_ammo_dump_cs_payout("staff_internal_car_500m", 3000, 2650) == 0


@pytest.mark.parametrize(("rule", "pay", "base", "expected_cs"), [
    (AMMO_DUMP_RULE_KEY, 3000, 2650, 88),
    (AMMO_DUMP_RULE_KEY, 2650, 2650, 0),
    ("staff_internal_car_500m", 2480, 2480, 0),
    ("staff_internal_aw_collision", 80, 80, 0),
    ("farm_halfcoin_120m", 1800, 1800, 0),
])
def test_all_direct_pay_rules_keep_worker_whole_with_only_unnamed_cs_share(
    rule, pay, base, expected_cs
):
    result = calculate_one_companion_one_guard_order_payout(
        rule_key=rule,
        total_amount=base,
        worker_roles=[("worker-1", "booster")],
        named_bonus_worker_ids=["worker-1"],
        customer_service_total_amount=pay,
    )
    assert result is not None
    assert result.worker_payouts[0].final_payout == base
    assert result.worker_payouts[0].named_bonus_amount == 0
    assert result.customer_service_payout == expected_cs
    assert pay - result.total_payout == pay - base - expected_cs


@pytest.mark.parametrize(("pay", "base", "cs", "retained"), [
    (3000, 2650, 88, 262),
    (2650, 2650, 0, 0),
])
def test_web_order_recalculation_persists_margin_based_cs_not_generic_25pct(
    pay, base, cs, retained,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        order = WebOrder(
            category="staff_internal",
            item="內部倒子彈 500M",
            order_rule_key=AMMO_DUMP_RULE_KEY,
            status="closed",
            amount=pay,
            customer_pay_amount=pay,
            payout_base_amount=base,
            customer_service_discord_id="cs-1",
            customer_service_display_name="客服",
        )
        db.add(order)
        db.flush()
        db.add(OrderAssignment(
            order_id=order.id,
            worker_discord_id="worker-1",
            worker_display_name="代肝",
            is_active=True,
            role_type="booster",
            has_named_bonus=True,
        ))
        db.flush()
        recalculate_order_payouts(db, order.id)
        db.flush()
        worker = db.query(WorkerPayout).filter_by(order_id=order.id).one()
        customer_service = db.query(CustomerServicePayout).filter_by(order_id=order.id).one()
        assert worker.final_payout == base
        assert customer_service.payout_amount == cs
        assert customer_service.rate == pytest.approx(cs / pay)
        assert pay - worker.final_payout - customer_service.payout_amount == retained


@pytest.mark.parametrize(("pay", "expected_cs"), [(2650, 0), (3000, 88)])
def test_accounting_policy_accepts_correct_special_margin_payout(pay, expected_cs):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE web_orders (
            id INTEGER PRIMARY KEY,
            status TEXT,
            amount INTEGER,
            customer_pay_amount INTEGER,
            payout_base_amount INTEGER,
            price_snapshot_json TEXT,
            order_rule_key TEXT
        );
        CREATE TABLE order_reports (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            status TEXT,
            is_legacy INTEGER
        );
        CREATE TABLE worker_payouts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            worker_discord_id TEXT,
            gross_share INTEGER,
            final_payout INTEGER,
            note TEXT
        );
        CREATE TABLE customer_service_payouts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            payout_amount INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO web_orders VALUES (1, 'closed', ?, ?, 2650, '{}', ?)",
        (pay, pay, AMMO_DUMP_RULE_KEY),
    )
    conn.execute("INSERT INTO order_reports VALUES (1, 1, 'approved', 0)")
    conn.execute(
        "INSERT INTO worker_payouts VALUES (1, 1, 'worker-1', 2650, 2650, ?)",
        ("特殊代肝單｜接單人員全額 100%｜無客服分潤及額外獎金",),
    )
    conn.execute("INSERT INTO customer_service_payouts VALUES (1, 1, ?)", (expected_cs,))
    state = _policy_consistency_for_order(conn, 1)
    assert state["worker_consistent"] is True
    assert state["cs_consistent"] is True
    conn.execute("UPDATE customer_service_payouts SET payout_amount = 0")
    if pay == 3000:
        assert _policy_consistency_for_order(conn, 1)["cs_consistent"] is False
    conn.close()
