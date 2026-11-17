"""Cross-source Discord dispatch cards share one order/payment state hierarchy."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from services.dispatch_embed_presentation import (
    dispatch_creation_placeholder, unify_dispatch_embed, display_payment,
)
from services import dispatch_embed_reconcile as repair
from services import orders
from services.acceptance.dispatch_presentation import apply_acceptance_dispatch_fields


def _fields(embed):
    return {str(field.name): str(field.value) for field in embed.fields}


def _assert_one_state(embed, status, payment):
    names = [str(field.name) for field in embed.fields]
    assert names[:2] == ["訂單狀態", "付款狀態"]
    assert names.count("訂單狀態") == names.count("付款狀態") == 1
    assert "狀態" not in names and "目前階段" not in names
    assert status in _fields(embed)["訂單狀態"]
    assert _fields(embed)["付款狀態"] == payment


@pytest.mark.parametrize("state,status,payment", [
    ("waiting_acceptance", "等待接單", "尚未付款"),
    ("accepted_pending_pay", "等待付款", "等待付款"),
    ("active", "服務進行中", "已付款"),
    ("stored", "已存單", "請依原付款紀錄確認"),
    ("closed", "已結單", "請依原付款紀錄確認"),
    ("cancelled", "已取消", "請依退款／付款紀錄確認"),
])
def test_same_card_layout_for_every_order_state(state, status, payment):
    card = discord.Embed(title="某一來源的舊派單標題")
    for field, value in (
        ("狀態", "接單完成｜等待付款"),
        ("顧客", "老闆甲"),
        ("票口", "<#1234>"),
        ("付款狀態", "已付款，接單人員已確認"),
        ("訂單", "三角洲｜娛樂陪"),
        ("商品原價", "1,200T"),
        ("目前階段", "等待付款"),
        ("打手分潤基準", "1,152T"),
        ("客服備註", "下午4點開始"),
    ):
        card.add_field(name=field, value=value)
    card.set_footer(text="WEB-42｜網站訂單")

    unify_dispatch_embed(card, status=state)
    _assert_one_state(card, status, payment)
    assert card.title == "魔丸娛樂｜接單面板"
    assert _fields(card)["打手分潤基準"] == "1,152T"
    assert _fields(card)["商品原價"] == "1,200T"
    assert card.footer.text == "WEB-42｜網站訂單"
    first = card.to_dict()
    unify_dispatch_embed(card, status=state)
    assert card.to_dict() == first


def test_paid_transition_erases_old_unpaid_state_even_when_input_was_stale():
    embed = discord.Embed(title="魔丸娛樂｜接單面板")
    embed.add_field(name="狀態", value="接單完成｜等待付款")
    embed.add_field(name="付款狀態", value="已付款，接單人員已確認")
    embed.add_field(name="目前階段", value="等待付款")
    embed.add_field(name="顧客實付", value="852T")

    unify_dispatch_embed(embed, status="active", paid_confirmed=True)
    _assert_one_state(embed, "服務進行中", "已付款")
    assert "等待付款" not in str(embed.to_dict())
    assert _fields(embed)["顧客實付"] == "852T"


def test_zero_amount_is_only_declared_after_canonical_active_status():
    assert display_payment("accepted_pending_pay", zero_amount=True) == "等待付款"
    assert display_payment("active", zero_amount=True) == "免付款（0T）"


def test_paid_store_retains_confirmed_payment_instead_of_reverting_to_waiting():
    guild = SimpleNamespace(get_member=lambda _uid: None)
    channel = SimpleNamespace(id=12345678, mention="<#12345678>", guild=guild)
    orders.configure_order_helpers({
        channel.id: {
            "status": "stored", "payment_confirmed": True,
            "customer_display_name": "老闆甲",
        }
    })
    card = orders.build_self_service_order_embed(
        customer_mention="老闆甲", category_label="三角洲",
        item="娛樂陪", quantity=1, payment_method="我的錢包",
        source_channel=channel,
    )
    _assert_one_state(card, "已存單", "已付款")


def test_overfull_dispatch_financial_details_are_compacted_not_lost():
    embed = discord.Embed(title="派單")
    for index in range(17):
        embed.add_field(name=f"一般資訊{index}", value=f"內容{index}")
    finance = (
        "商品原價", "百分比折扣", "固定折扣", "點數折價", "指定費",
        "顧客實付", "打手分潤基準", "加急費", "店家實留",
    )
    for index, name in enumerate(finance):
        embed.add_field(name=name, value=f"{index + 10:,}T")
    unify_dispatch_embed(embed, status="active")
    assert len(embed.fields) <= 25
    text = str(embed.to_dict())
    for name in finance:
        assert name in text
    assert "金額明細" in text


def test_web_placeholder_uses_same_title_fields_and_retry_marker():
    embed = dispatch_creation_placeholder(
        order_id=42, customer_mention="<@1234>", category="三角洲",
        item="娛樂陪",
    )
    _assert_one_state(embed, "等待接單", "尚未付款")
    assert embed.title == "魔丸娛樂｜接單面板"
    assert embed.footer.text == "WEB-42｜網站訂單"
    assert _fields(embed)["訂單"] == "三角洲｜娛樂陪"


def test_discord_and_web_builders_share_same_layout_and_customer_privacy():
    guild = SimpleNamespace(get_member=lambda _uid: SimpleNamespace(display_name="老闆甲"))
    channel = SimpleNamespace(id=987654321, mention="<#987654321>", guild=guild)
    selections = {channel.id: {
        "status": "accepted_pending_pay", "customer_display_name": "老闆甲",
        "item": "三角洲", "quantity": 2,
    }}
    orders.configure_order_helpers(selections)

    dc = orders.build_self_service_order_embed(
        customer_mention="<@123456789123456789>", category_label="三角洲",
        item="娛樂陪", quantity=2, payment_method="待付款",
        source_channel=channel, receiver_text="阿明",
    )
    _assert_one_state(dc, "等待付款", "等待付款")
    selections[channel.id]["status"] = "active"
    paid = orders.build_self_service_order_embed(
        customer_mention="<@123456789123456789>", category_label="三角洲",
        item="娛樂陪", quantity=2, payment_method="轉帳",
        source_channel=channel, receiver_text="阿明",
    )
    _assert_one_state(paid, "服務進行中", "已付款")
    assert _fields(paid)["顧客"] == "老闆甲"

    # The acceptance snapshot overrides an older ticket cache by design.
    selections[channel.id]["status"] = "accepted_pending_pay"
    apply_acceptance_dispatch_fields(
        paid, {"status": "active", "accepted_count": 1, "required_staff_count": 1}
    )
    _assert_one_state(paid, "服務進行中", "已付款")


class FakeMessage:
    def __init__(self, embed):
        self.embeds = [embed]
        self.edited = 0
        self.view = "original persistent controls"

    async def edit(self, **kwargs):
        self.embeds = [kwargs["embed"]]
        self.edited += 1


class FakeChannel:
    def __init__(self, message):
        self.message = message

    async def fetch_message(self, message_id):
        assert message_id == 555
        return self.message


def test_existing_paid_discord_card_is_repaired_without_new_message_or_db_write(monkeypatch):
    stale = discord.Embed(title="魔丸娛樂｜接單面板")
    stale.add_field(name="狀態", value="接單完成｜等待付款")
    stale.add_field(name="付款狀態", value="已付款，接單人員已確認")
    stale.add_field(name="付款方式", value="待付款")
    stale.add_field(name="商品原價", value="1,200T")
    stale.set_footer(text="魔丸娛樂｜接單系統")
    msg = FakeMessage(stale)
    guild = SimpleNamespace(get_channel=lambda _id: FakeChannel(msg))
    bot = SimpleNamespace(get_guild=lambda _id: guild)
    monkeypatch.setattr(repair, "_recent_paid_orders", lambda *, limit: [{
        "id": 42, "dispatch_channel_id": "777", "dispatch_message_id": "555",
        "payment_method": "轉帳", "amount": 852,
    }])

    assert asyncio.run(repair.reconcile_recent_paid_dispatch_embeds(bot, 123)) == 1
    _assert_one_state(msg.embeds[0], "服務進行中", "已付款")
    assert _fields(msg.embeds[0])["付款方式"] == "轉帳"
    assert _fields(msg.embeds[0])["商品原價"] == "1,200T"
    assert msg.embeds[0].footer.text == "魔丸娛樂｜接單系統"
    assert msg.view == "original persistent controls"
    assert asyncio.run(repair.reconcile_recent_paid_dispatch_embeds(bot, 123)) == 0
    assert msg.edited == 1


def test_dispatch_lifecycle_producers_use_shared_contract_without_second_status():
    root = Path(__file__).resolve().parents[1]
    def source(name):
        return (root / name).read_text(encoding="utf-8")

    assert "unify_dispatch_embed(" in source("services/order_payment_runtime.py")
    assert "claim_data[\"payment_confirmed\"] = True" in source("services/order_payment_runtime.py")
    assert "unify_dispatch_embed(" in source("services/acceptance/dispatch_presentation.py")
    assert "dispatch_creation_placeholder(" in source("services/web_sync/order_created.py")
    for name in (
        "services/order_payment_runtime.py",
        "services/order_storage_runtime.py",
        "services/order_dispatch_runtime.py",
    ):
        assert 'name="狀態"' not in source(name)
    assert "paid_dispatch_embed_reconcile_worker" not in source(
        "services/acceptance/sync_worker.py"
    )
