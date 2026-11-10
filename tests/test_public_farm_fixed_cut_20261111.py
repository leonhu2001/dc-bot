"""Fixed shop-cut Delta farming: all tiers and both order entry paths.

The policy is independent of worker performance, naming and store affiliation.
Every amount is an integer T; ties go to CS (half-up).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.farm_fixed_cut_policy import (
    PUBLIC_FARM_FIXED_CUTS,
    calculate_farm_fixed_cut_financials,
    calculate_farm_fixed_cut_settlement,
    is_public_farm_fixed_cut_rule,
)
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
    is_full_worker_payout_rule,
)
from services.order_rules import ORDER_RULES, calculate_price, get_allowed_role_ids
from services.orders import get_order_item_details_for_group
from shared.db import Base
from shared.models import (
    CustomerServicePayout, OrderAssignment, WebOrder, WorkerPayout,
)
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.order_service import recalculate_order_payouts


EXPECTED = {
    "farm_ammo_dump_100m": (800, 90, 710, 23, 67),
    "farm_ammo_dump_200m": (1500, 150, 1350, 38, 112),
    "farm_ammo_dump_300m": (2100, 180, 1920, 45, 135),
    "farm_ammo_dump_500m": (3300, 200, 3100, 50, 150),
    "farm_ammo_dump_1000m": (6400, 400, 6000, 100, 300),
    "farm_ammo_dump_2000m": (11500, 600, 10900, 150, 450),
    "farm_car_crash_100m": (700, 80, 620, 20, 60),
    "farm_car_crash_200m": (1400, 120, 1280, 30, 90),
    "farm_car_crash_500m": (3250, 150, 3100, 38, 112),
    "farm_car_crash_1000m": (6100, 300, 5800, 75, 225),
}


@pytest.mark.parametrize("key,values", EXPECTED.items())
def test_shared_rules_discord_web_preview_and_fixed_wage_settlement(key, values):
    price, cut, worker_wage, cs, retained = values
    assert PUBLIC_FARM_FIXED_CUTS[key] == (price, cut)
    rule = ORDER_RULES[key]
    assert rule.category == "farm"
    assert rule.pricing_type == "fixed"
    assert rule.price == price
    assert rule.required_staff_count == 1
    assert rule.allowed_roles == ("halfcoin_receiver",)
    assert get_allowed_role_ids(rule)
    assert not rule.allow_specify
    assert not rule.vip_discount_allowed
    assert not rule.point_benefits_allowed
    assert not rule.loyalty_benefits_enabled
    assert is_public_farm_fixed_cut_rule(key)
    assert is_full_worker_payout_rule(key)
    price_result = calculate_price(rule, quantity=1)
    finance = calculate_farm_fixed_cut_financials(rule, price_result, {})
    assert finance["customer_pay_amount"] == price
    assert finance["payout_base_amount"] == worker_wage
    assert finance["store_margin_amount"] == cut
    assert finance["customer_service_payout_amount"] == cs
    assert finance["store_retained_amount"] == retained
    settlement = calculate_farm_fixed_cut_settlement(key, price, worker_wage)
    assert settlement.fixed_store_cut == cut
    assert settlement.worker_amount == worker_wage
    assert settlement.customer_service_amount == cs
    assert settlement.store_retained_amount == retained
    assert price == worker_wage + cs + retained

    result = calculate_one_companion_one_guard_order_payout(
        rule_key=key,
        total_amount=worker_wage,
        worker_roles=[("worker-1", "booster")],
        named_bonus_worker_ids=["worker-1"],
        customer_service_total_amount=price,
    )
    assert result is not None
    assert len(result.worker_payouts) == 1
    assert result.worker_payouts[0].base_rate == 1.0
    assert result.worker_payouts[0].final_payout == worker_wage
    assert result.customer_service_payout == cs


def test_all_tiers_are_visible_to_discord_and_web_and_mouth_organ_is_retired():
    groups = get_grouped_order_catalog("farm")
    web = {g["key"]: g for g in groups}
    for key, group_label, prefix in [
        ("ammo_dump", "倒子彈代肝", "farm_ammo_dump_"),
        ("car_crash", "撞車代肝", "farm_car_crash_"),
    ]:
        group = web[key]
        assert group["label"] == group_label
        discord_rows = get_order_item_details_for_group("farm", group_label)
        expected_keys = {
            candidate for candidate in EXPECTED if candidate.startswith(prefix)
        }
        assert {item["rule_key"] for item in group["variants"]} == expected_keys
        assert {item["rule_key"] for item in discord_rows} == expected_keys
        assert all(item["price"] == ORDER_RULES[item["rule_key"]].price for item in group["variants"])


@pytest.mark.parametrize("key,values", EXPECTED.items())
def test_closed_order_recalculation_preserves_worker_wages_and_cs_split(key, values):
    price, cut, worker_wage, cs, retained = values
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        order = WebOrder(
            category="farm", item=key, order_rule_key=key, status="closed",
            amount=price, customer_pay_amount=price,
            payout_base_amount=worker_wage, closed_at=datetime(2026, 11, 11),
        )
        db.add(order)
        db.flush()
        db.add(OrderAssignment(
            order_id=order.id, worker_discord_id="worker-1",
            is_active=True, has_named_bonus=True, role_type="booster",
        ))
        db.flush()
        recalculate_order_payouts(db, order.id)
        db.flush()
        wages = db.query(WorkerPayout).filter_by(order_id=order.id).one()
        css = db.query(CustomerServicePayout).filter_by(order_id=order.id).one()
        assert int(round(wages.final_payout)) == worker_wage
        assert int(round(wages.base_payout)) == worker_wage
        assert css.payout_amount == cs
        assert css.rate == pytest.approx(cs / price)
        assert price - wages.final_payout - css.payout_amount == retained


@pytest.mark.parametrize("key,values", EXPECTED.items())
def test_wrong_worker_base_is_blocked_not_replaced_by_generic_80pct(key, values):
    price, _, worker_wage, _, _ = values
    with pytest.raises(ValueError, match="固定店抽"):
        calculate_farm_fixed_cut_settlement(key, price, worker_wage - 1)
    with pytest.raises(ValueError, match="固定店抽"):
        calculate_one_companion_one_guard_order_payout(
            rule_key=key, total_amount=worker_wage - 1,
            worker_roles=[("worker-1", "booster")],
            customer_service_total_amount=price,
        )
    with pytest.raises(ValueError, match="一名"):
        calculate_one_companion_one_guard_order_payout(
            rule_key=key, total_amount=worker_wage,
            worker_roles=[("w1", "booster"), ("w2", "booster")],
            customer_service_total_amount=price,
        )


def test_wallet_is_payment_not_discount_on_public_checkout(monkeypatch):
    from web.app.services import checkout_preview as checkout
    monkeypatch.setattr(
        checkout, "load_customer_state",
        lambda *_: {"vip_name": "白金", "points": 100, "wallet_balance": 200},
    )
    monkeypatch.setattr(
        checkout, "vip_discount_policy",
        lambda **kwargs: {"eligible": True, "pay_rate": 94, "reason": "測試折扣"},
    )
    monkeypatch.setattr(
        checkout, "preview_same_order_benefit", lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        checkout, "resolve_selected_staff", lambda **kwargs: ([], []),
    )
    preview = checkout.build_checkout_preview(
        customer_id="worker-fixed-cut-test",
        rule_key="farm_ammo_dump_100m",
        use_wallet=True,
    )
    finance = preview["finance"]
    assert finance["customer_pay_amount"] == 800
    assert finance["wallet_use_amount"] == 200
    assert finance["remaining_pay_amount"] == 600
    assert finance["payout_base_amount"] == 710
    assert finance["store_margin_amount"] == 90
    assert finance["customer_service_payout_amount"] == 23
    assert preview["vip"]["pay_rate"] == 100
