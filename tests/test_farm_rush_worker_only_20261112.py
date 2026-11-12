"""Public and internal Delta coin-wash rush allocation regression.

Rush is a product choice. It must affect only customer charge and worker wages,
never the normal fixed store cut or customer-service commission.
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.farm_fixed_cut_policy import (
    _BASE_PUBLIC_FARM_FIXED_CUTS, PUBLIC_FARM_FIXED_CUTS,
    PUBLIC_FARM_RUSH_FEE, calculate_farm_fixed_cut_settlement,
)
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RULE_KEY, AMMO_DUMP_RUSH_RULE_KEY,
    calculate_internal_ammo_dump_cs_payout,
    calculate_internal_ammo_dump_financials, INTERNAL_RUSH_FEE,
)
from services.order_rules import ORDER_RULES, calculate_price
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout, is_full_worker_payout_rule,
)
from services.orders import get_order_item_details_for_group
from services.self_service_financials import calculate_self_service_financials
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.order_service import recalculate_order_payouts
from shared.db import Base
from shared.models import WebOrder, OrderAssignment, WorkerPayout, CustomerServicePayout


@pytest.mark.parametrize("key,normal", sorted(_BASE_PUBLIC_FARM_FIXED_CUTS.items()))
def test_public_rush_adds_exactly_280_to_worker_not_store_or_cs(key, normal):
    price, cut = normal
    rush_key = f"{key}_rush"
    assert PUBLIC_FARM_RUSH_FEE == 280
    assert PUBLIC_FARM_FIXED_CUTS[rush_key] == (price + 280, cut)
    assert ORDER_RULES[rush_key].price == price + 280
    assert "加急" in ORDER_RULES[rush_key].label
    assert is_full_worker_payout_rule(rush_key)

    normal_settle = calculate_farm_fixed_cut_settlement(key, price)
    rush_settle = calculate_farm_fixed_cut_settlement(rush_key, price + 280)
    assert rush_settle.worker_amount == normal_settle.worker_amount + 280
    assert rush_settle.fixed_store_cut == normal_settle.fixed_store_cut
    assert rush_settle.customer_service_amount == normal_settle.customer_service_amount
    assert rush_settle.store_retained_amount == normal_settle.store_retained_amount
    assert (rush_settle.worker_amount + rush_settle.customer_service_amount
            + rush_settle.store_retained_amount) == price + 280
    finance = calculate_self_service_financials(
        ORDER_RULES[rush_key], calculate_price(ORDER_RULES[rush_key], quantity=1), {}
    )
    assert finance["customer_pay_amount"] == price + 280
    assert finance["payout_base_amount"] == rush_settle.worker_amount
    assert finance["farm_rush_fee"] == 280
    assert finance["store_margin_amount"] == cut

    payout = calculate_one_companion_one_guard_order_payout(
        rule_key=rush_key, total_amount=rush_settle.worker_amount,
        worker_roles=[("worker", "booster")],
        customer_service_total_amount=price + 280,
        named_bonus_worker_ids=["worker"],
    )
    assert payout.total_worker_payout == rush_settle.worker_amount
    assert payout.worker_payouts[0].named_bonus_amount == 0
    assert payout.customer_service_payout == rush_settle.customer_service_amount


@pytest.mark.parametrize("named,normal_price", [(True, 2650), (False, 3000)])
def test_internal_ammo_rush_named_and_unnamed_260_all_to_worker(named,normal_price):
    assert INTERNAL_RUSH_FEE == 260
    expected_store = 0 if named else 350
    expected_cs = 0 if named else 88
    for key, extra in ((AMMO_DUMP_RULE_KEY,0),(AMMO_DUMP_RUSH_RULE_KEY,260)):
        rule = ORDER_RULES[key]
        data = {"staff_internal_ammo_named":named,"order_rule_key":key,
                "manual_discount_percent":40,"cash_coupon_amount":500}
        finance = calculate_self_service_financials(rule,calculate_price(rule,quantity=1),data)
        assert finance["customer_pay_amount"] == normal_price + extra
        assert finance["payout_base_amount"] == 2650 + extra
        assert finance["store_margin_amount"] == expected_store
        assert finance["customer_service_payout_amount"] == expected_cs
        assert finance["store_retained_amount"] == expected_store - expected_cs
        assert finance["farm_rush_fee"] == extra
        assert calculate_internal_ammo_dump_cs_payout(
            key,normal_price + extra,2650 + extra
        ) == expected_cs
        result=calculate_one_companion_one_guard_order_payout(
            rule_key=key,total_amount=2650 + extra,
            worker_roles=[("worker","booster")],
            customer_service_total_amount=normal_price + extra,
        )
        assert result.worker_payouts[0].final_payout == 2650 + extra
        assert result.customer_service_payout == expected_cs


def test_internal_car_rush_has_zero_shop_cut_and_zero_cs():
    normal=ORDER_RULES["staff_internal_car_500m"]
    rush=ORDER_RULES["staff_internal_car_500m_rush"]
    assert normal.price==2480
    assert rush.price==2740
    assert is_full_worker_payout_rule(rush.key)
    quote=calculate_self_service_financials(rush,calculate_price(rush,quantity=1),{})
    assert quote["customer_pay_amount"]==2740
    assert quote["payout_base_amount"]==2740
    result=calculate_one_companion_one_guard_order_payout(
        rule_key=rush.key,total_amount=2740,
        worker_roles=[("worker","booster")],
        customer_service_total_amount=2740,
    )
    assert result.worker_payouts[0].final_payout==2740
    assert result.customer_service_payout==0


def test_discord_and_web_rush_catalog_are_identical_and_fully_qualified():
    groups={group["key"]:group for group in get_grouped_order_catalog("farm")}
    for kind,name,count in (
        ("ammo_dump","倒子彈代肝",6),
        ("car_crash","撞車代肝",4),
    ):
        prefix=f"farm_{kind}_"
        discord={x["rule_key"] for x in get_order_item_details_for_group("farm",name)}
        web={x["rule_key"] for x in groups[kind]["variants"]}
        assert discord==web
        assert len(discord)==2*count
        assert sum(key.endswith("_rush") for key in web)==count
        for key in web:
            assert ORDER_RULES[key].allowed_roles==("halfcoin_receiver",)
    for group,name in (("倒子彈｜500M","ammo_dump"),
                       ("撞車｜500M","car")):
        rows=get_order_item_details_for_group("staff_internal",group)
        assert len(rows)==2
        assert rows[0]["rule_key"].startswith("staff_internal_")
        assert rows[1]["rule_key"].endswith("_rush")


@pytest.mark.parametrize("key",["farm_ammo_dump_100m_rush","farm_car_crash_1000m_rush",
                                 "staff_internal_ammo_dump_500m_rush","staff_internal_car_500m_rush"])
def test_closed_order_worker_wage_not_deducted_again_on_report(key):
    # Completed/closed order snapshots are based on worker wage, not sale amount.
    if key.startswith("farm_"):
        price,cut=PUBLIC_FARM_FIXED_CUTS[key]
        wages=price-cut
        cs=calculate_farm_fixed_cut_settlement(key,price).customer_service_amount
    elif "ammo_dump" in key:
        price,wages,cs=3260,2910,88
    else:
        price,wages,cs=2740,2740,0
    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE order_acceptance_meta (order_id INTEGER PRIMARY KEY,status TEXT)")
    with Session(engine) as db:
        order=WebOrder(category="farm" if key.startswith("farm_") else "staff_internal",
            item=key,order_rule_key=key,status="closed",amount=price,
            customer_pay_amount=price,payout_base_amount=wages,
            closed_at=datetime(2026,11,12))
        db.add(order);db.flush()
        db.add(OrderAssignment(order_id=order.id,worker_discord_id="worker",
            is_active=True,has_named_bonus=True,role_type="booster"))
        db.flush()
        recalculate_order_payouts(db,order.id)
        db.flush()
        worker=db.query(WorkerPayout).filter_by(order_id=order.id).one()
        worker_payout=round(float(worker.final_payout))
        assert worker_payout==wages
        css=db.query(CustomerServicePayout).filter_by(order_id=order.id).all()
        cs_paid=sum(int(x.payout_amount or 0) for x in css)
        assert cs_paid==cs
        assert price-wages-cs==(
            0 if key=="staff_internal_car_500m_rush"
            else 262 if key=="staff_internal_ammo_dump_500m_rush"
            else PUBLIC_FARM_FIXED_CUTS[key][1]-cs
        )
