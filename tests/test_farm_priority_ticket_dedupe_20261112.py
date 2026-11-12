"""Regression contracts: public +280, internal +260 and idempotent ticket panels.

All charges are exact integer T; priority fees go only to assigned worker,
never to the fixed shop cut, CS percentage, discount or named bonus.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.farm_fixed_cut_policy import (
    BASE_PUBLIC_FARM_FIXED_CUTS,
    PUBLIC_FARM_FIXED_CUTS,
    PUBLIC_FARM_PRIORITY_FEE,
    calculate_farm_fixed_cut_settlement,
    public_farm_priority_fee,
)
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
    is_full_worker_payout_rule,
)
from services.order_rules import ORDER_RULES, calculate_price
from services.orders import get_order_item_details_for_group
from services.self_service_financials import calculate_self_service_financials
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_RUSH_RULE_KEY,
    INTERNAL_PRIORITY_FEE,
)
from services.quick_order_ticket_dedupe_policy import (
    message_is_self_service_panel, has_self_service_panel,
    send_self_service_panel_once,
)
from web.app.services.order_groups import get_grouped_order_catalog


@pytest.mark.parametrize("key,base", sorted(BASE_PUBLIC_FARM_FIXED_CUTS.items()))
def test_public_urgency_280_is_only_worker_money(key, base):
    price, cut = base
    rush_key = key + "_rush"
    assert PUBLIC_FARM_PRIORITY_FEE == 280
    assert PUBLIC_FARM_FIXED_CUTS[rush_key] == (price+280, cut)
    assert public_farm_priority_fee(key) == 0
    assert public_farm_priority_fee(rush_key) == 280
    rule = ORDER_RULES[rush_key]
    assert rule.price == price+280
    assert not rule.vip_discount_allowed
    assert not rule.point_benefits_allowed
    assert not rule.loyalty_benefits_enabled
    standard = calculate_farm_fixed_cut_settlement(key, price)
    rush = calculate_farm_fixed_cut_settlement(rush_key, price+280)
    assert rush.worker_amount == standard.worker_amount+280
    assert rush.fixed_store_cut == standard.fixed_store_cut == cut
    assert rush.customer_service_amount == standard.customer_service_amount
    assert rush.store_retained_amount == standard.store_retained_amount
    fin = calculate_self_service_financials(
        rule, calculate_price(rule,quantity=1),
        {"manual_discount_percent":50,"cash_coupon_amount":2000}
    )
    assert fin["customer_pay_amount"] == price+280
    assert fin["payout_base_amount"] == rush.worker_amount
    assert fin["priority_fee_amount"] == 280
    assert fin["priority_fee_receiver"] == "worker"
    assert fin["store_margin_amount"] == cut
    settlement = calculate_one_companion_one_guard_order_payout(
        rule_key=rush_key,total_amount=rush.worker_amount,
        worker_roles=[("booster","booster")],
        customer_service_total_amount=price+280
    )
    assert settlement.worker_payouts[0].final_payout == rush.worker_amount
    assert settlement.customer_service_payout == rush.customer_service_amount


@pytest.mark.parametrize("rule_key,named,price,worker,cs,store", [
    ("staff_internal_ammo_dump_500m",True,2650,2650,0,0),
    ("staff_internal_ammo_dump_500m",False,3000,2650,88,262),
    ("staff_internal_ammo_dump_500m_rush",True,2910,2910,0,0),
    ("staff_internal_ammo_dump_500m_rush",False,3260,2910,88,262),
    ("staff_internal_car_500m",None,2480,2480,0,0),
    ("staff_internal_car_500m_rush",None,2740,2740,0,0),
])
def test_internal_farm_priority_gives_booster_full_fee_and_never_adds_shop_or_cs(
    rule_key,named,price,worker,cs,store,
):
    assert is_full_worker_payout_rule(rule_key)
    rule=ORDER_RULES[rule_key]
    kwargs={"manual_discount_percent":50,"cash_coupon_amount":1000}
    if named is not None:
        kwargs["staff_internal_ammo_named"]=named
    finance=calculate_self_service_financials(rule,calculate_price(rule,quantity=1),kwargs)
    assert finance["customer_pay_amount"]==price
    assert finance["payout_base_amount"]==worker
    assert finance.get("customer_service_payout_amount",0)==cs
    assert finance.get("store_retained_amount",0)==store
    assert finance["priority_fee_amount"]==(INTERNAL_PRIORITY_FEE if rule_key.endswith("_rush") else 0)
    settlement=calculate_one_companion_one_guard_order_payout(
        rule_key=rule_key,total_amount=worker,
        worker_roles=[("booster","booster")],
        customer_service_total_amount=price
    )
    assert settlement.worker_payouts[0].final_payout==worker
    assert settlement.customer_service_payout==cs
    assert price==worker+cs+store


def test_public_web_and_discord_offer_normal_and_priority_variant_for_each_size():
    groups = {g["key"]:g for g in get_grouped_order_catalog("farm")}
    for group_name,category,prefix,n in [
        ("倒子彈代肝","ammo_dump","farm_ammo_dump_",6),
        ("撞車代肝","car_crash","farm_car_crash_",4),
    ]:
        web=groups[category]["variants"]
        bot=get_order_item_details_for_group("farm",group_name)
        keys={x["rule_key"] for x in web}
        expected={key for key in PUBLIC_FARM_FIXED_CUTS if key.startswith(prefix)}
        assert len(expected)==n*2
        assert {x["rule_key"] for x in bot}==keys==expected
        assert sum(key.endswith("_rush") for key in keys)==n


def test_internal_options_offer_two_spec_tiers_but_do_not_rush_aw():
    ammo=get_order_item_details_for_group("staff_internal","倒子彈｜500M")
    car=get_order_item_details_for_group("staff_internal","撞車｜500M")
    assert [x["rule_key"] for x in ammo]==[
        "staff_internal_ammo_dump_500m","staff_internal_ammo_dump_500m_rush",
    ]
    assert [x["rule_key"] for x in car]==[
        "staff_internal_car_500m","staff_internal_car_500m_rush",
    ]
    aw=get_order_item_details_for_group("staff_internal","AW 子彈")
    assert [x["rule_key"] for x in aw]==["staff_internal_aw_collision"]


def test_ticket_panel_duplicate_detection_checks_ownership_and_selectors():
    component=SimpleNamespace(custom_id="self_service_order_detail_select")
    row=SimpleNamespace(children=[component])
    message=SimpleNamespace(
        author=SimpleNamespace(id=42),components=[row],embeds=[]
    )
    assert message_is_self_service_panel(message,42)
    assert not message_is_self_service_panel(message,43)
    embed_only=SimpleNamespace(
        author=SimpleNamespace(id=42),components=[],
        embeds=[SimpleNamespace(title="🛒 三角洲")],
    )
    assert message_is_self_service_panel(embed_only,42)


def test_same_ticket_never_receives_duplicate_self_service_panel():
    class Channel:
        def __init__(self):
            self.guild=SimpleNamespace(me=SimpleNamespace(id=42))
            self.messages=[]
        async def history(self,**kwargs):
            for msg in self.messages[::-1]:
                yield msg
        async def send(self,*,embed,view,allowed_mentions):
            self.messages.append(SimpleNamespace(
                author=SimpleNamespace(id=42),components=[],
                embeds=[embed],
            ))
    async def run():
        ch=Channel()
        embed=SimpleNamespace(title="自助下單")
        first=await send_self_service_panel_once(
            ch,embed=embed,view=object(),allowed_mentions=None
        )
        second=await send_self_service_panel_once(
            ch,embed=embed,view=object(),allowed_mentions=None
        )
        assert first is True and second is False
        assert len(ch.messages)==1
        assert await has_self_service_panel(ch)
    asyncio.run(run())


def test_rapid_confirm_retries_and_multiple_confirm_views_do_not_create_two_tickets(monkeypatch):
    import services.quick_order_v2 as q
    async def run():
        q._RECENT_TICKET_SUCCESS.clear()
        q._TICKET_CREATE_IN_FLIGHT.clear()
        created=0
        async def create(interaction,**kwargs):
            nonlocal created
            created+=1
            await asyncio.sleep(0.03)
            return SimpleNamespace(id=123456)
        monkeypatch.setattr(q,"_create_ticket",create)
        a=q.QuickOrderConfirmView(customer_id=123,category="farm",item_group="倒子彈代肝",source_channel_id=8)
        b=q.QuickOrderConfirmView(customer_id=123,category="farm",item_group="倒子彈代肝",source_channel_id=8)
        def interaction():
            return SimpleNamespace(
                user=SimpleNamespace(id=123),
                response=SimpleNamespace(send_message=AsyncMock()),
            )
        first,second=interaction(),interaction()
        await asyncio.gather(a.children[0].callback(first),
                             b.children[0].callback(second))
        assert created==1
        assert second.response.send_message.await_count+first.response.send_message.await_count==1
        third=interaction()
        await b.children[0].callback(third)
        third.response.send_message.assert_awaited_once()
        assert "剛剛已建立" in third.response.send_message.await_args.args[0]
        assert created==1
        q._RECENT_TICKET_SUCCESS.clear()
    asyncio.run(run())


@pytest.mark.parametrize("key,customer,worker,cs", [
    ("staff_internal_ammo_dump_500m_rush", 2910, 2910, 0),
    ("staff_internal_ammo_dump_500m_rush", 3260, 2910, 88),
    ("staff_internal_car_500m_rush", 2740, 2740, 0),
])
def test_internal_rush_closed_salary_and_report_approval_keep_full_worker_and_original_cs(
    monkeypatch, key, customer, worker, cs,
):
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from shared.db import Base
    from shared.models import WebOrder, OrderAssignment, WorkerPayout, CustomerServicePayout
    from web.app.services.order_service import recalculate_order_payouts
    from web.app.services import worker_bonus_payout as bonuses

    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as con:
        con.exec_driver_sql(
            "CREATE TABLE order_acceptance_meta (order_id INTEGER PRIMARY KEY, status TEXT)"
        )
    with Session(engine) as db:
        order=WebOrder(
            category="staff_internal",item=key,order_rule_key=key,status="closed",
            amount=customer,customer_pay_amount=customer,
            payout_base_amount=worker,closed_at=datetime(2026,11,12),
        )
        db.add(order)
        db.flush()
        db.add(OrderAssignment(
            order_id=order.id,worker_discord_id="booster",
            role_type="booster",is_active=True,has_named_bonus=True,
        ))
        db.flush()
        recalculate_order_payouts(db,order.id)
        db.commit()
        order_id=order.id
        salary=db.query(WorkerPayout).filter_by(order_id=order_id).one()
        cs_row=db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
        assert salary.final_payout==worker
        assert cs_row.payout_amount==cs
        assert salary.base_rate==1.0
        assert customer==worker+cs+(customer-worker-cs)

    monkeypatch.setattr(bonuses,"SessionLocal",lambda: Session(engine))
    def forbidden(*args,**kwargs):
        raise AssertionError("priority full-worker payout must not query performance bonus")
    monkeypatch.setattr(bonuses,"previous_month_performance",forbidden)
    monkeypatch.setattr(bonuses,"is_store_binding_effective_at",forbidden)
    monkeypatch.setattr(bonuses,"_approved_stream_map",forbidden)
    monkeypatch.setattr(bonuses,"_assignment_stream_override_map",forbidden)
    bonuses.apply_approved_report_worker_bonuses(order_id)
    with Session(engine) as db:
        salary=db.query(WorkerPayout).filter_by(order_id=order_id).one()
        cs_row=db.query(CustomerServicePayout).filter_by(order_id=order_id).one()
        assert salary.final_payout==worker
        assert salary.base_rate==1.0
        assert salary.named_bonus_amount==0
        assert "加急+260T" in salary.note
        if cs:
            assert "客服固定88T" in salary.note
        assert cs_row.payout_amount==cs
        assert customer-worker-cs==(262 if cs else 0)


def test_public_web_priority_wallet_and_vip_discount_cannot_take_worker_fee(monkeypatch):
    from web.app.services import checkout_preview as checkout
    monkeypatch.setattr(
        checkout,"load_customer_state",
        lambda *_: {"vip_name":"白金","points":100,"wallet_balance":200},
    )
    monkeypatch.setattr(
        checkout,"vip_discount_policy",
        lambda **kwargs: {"eligible":True,"pay_rate":94,"reason":"測試折扣"},
    )
    monkeypatch.setattr(checkout,"preview_same_order_benefit",lambda *a,**kw:None)
    monkeypatch.setattr(checkout,"resolve_selected_staff",lambda **kwargs:([],[]))
    preview=checkout.build_checkout_preview(
        customer_id="farm-rush-wallet-test",
        rule_key="farm_ammo_dump_100m_rush",use_wallet=True,
    )
    finance=preview["finance"]
    assert finance["customer_pay_amount"]==1080
    assert finance["wallet_use_amount"]==200
    assert finance["remaining_pay_amount"]==880
    assert finance["payout_base_amount"]==990
    assert finance["store_margin_amount"]==90
    assert finance["customer_service_payout_amount"]==23
    assert finance["store_retained_amount"]==67
    assert finance["priority_fee_amount"]==280
    assert preview["vip"]["pay_rate"]==100


def test_existing_bot_customer_service_dispatch_calls_idempotent_sender():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/"bot.py").read_text(encoding="utf-8")
    assert 'from services.quick_order_ticket_dedupe_policy import send_legacy_control_panel_once' in s
    source=(Path(__file__).resolve().parents[1]/"services/quick_order_ticket_dedupe_policy.py").read_text(encoding="utf-8")
    assert "這個下單票口已經有自助下單面板" in source
