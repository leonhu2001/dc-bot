from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from services.order_customer_anonymity import (
    ANONYMOUS_BOSS_LABEL,
    customer_name_is_anonymous,
    customer_name_is_anonymous_in_snapshot,
    public_customer_display_name,
)
from services import orders
from services import self_service_ui_runtime as ui

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value,expected", [
    ({"anonymous_customer_name": True}, True),
    ({"anonymous_customer_name": False}, False),
    ({"anonymous_customer_name": "true"}, False),
    ({}, False),
])
def test_anonymity_requires_explicit_boolean_choice(value, expected):
    assert customer_name_is_anonymous(value) is expected
    assert customer_name_is_anonymous_in_snapshot(json.dumps(value)) is expected


def test_public_anonymity_does_not_mutate_actual_customer_identity():
    snapshot = {"anonymous_customer_name": True, "manual_staff_amount": 2000}
    actual = "顧客真的名字"
    assert public_customer_display_name(actual, anonymous=True) == ANONYMOUS_BOSS_LABEL
    assert public_customer_display_name(actual, anonymous=False) == actual
    assert actual == "顧客真的名字"
    assert snapshot["manual_staff_amount"] == 2000


def test_note_modal_contains_real_modal_dropdown_for_name_visibility():
    modal = ui.SelfServiceSubmitNoteModal(123, 456)
    label = modal.anonymous_name
    assert isinstance(label, discord.ui.Label)
    assert isinstance(label.component, discord.ui.Select)
    assert [option.value for option in label.component.options] == ["no", "yes"]
    assert label.component.required is True
    assert modal.note.required is False
    assert "是否匿名" in label.text


@pytest.mark.parametrize("choice,expected", [("yes", True), ("no", False)])
def test_staff_choice_is_saved_before_order_is_dispatched(monkeypatch, choice, expected):
    channel_id = 456
    data = {"order_rule_key": "custom_custom_order", "customer_display_name": "阿珍"}
    monkeypatch.setattr(ui, "SELF_SERVICE_ORDER_SELECTIONS", {channel_id: data})
    monkeypatch.setattr(ui, "ORDER_CLAIMS", {})
    monkeypatch.setattr(ui, "remember_order_data", lambda _id, _data: None)
    monkeypatch.setattr(ui, "is_customer_staff", lambda _user: True)

    class FakeMember:
        id = 7654321

    monkeypatch.setattr(ui.discord, "Member", FakeMember)
    observations = []

    async def fake_dispatch(_interaction, *, customer_id, channel_id):
        observations.append(dict(data))
        return "已送單"

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(ui, "create_waiting_acceptance_order_from_self_service", fake_dispatch)
    monkeypatch.setattr(ui, "log_self_service_proxy_action", fake_log)

    modal = ui.SelfServiceSubmitNoteModal(123, channel_id)
    modal.anonymous_name.component._values = [choice]
    interaction = SimpleNamespace(
        user=FakeMember(),
        channel=None,
        guild=None,
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    asyncio.run(modal.on_submit(interaction))
    assert observations and observations[0]["anonymous_customer_name"] is expected
    assert data["customer_display_name"] == "阿珍"
    interaction.followup.send.assert_awaited_once_with("已送單", ephemeral=True)


def test_discord_dispatch_embed_hides_name_and_ticket_channel_when_anonymous(monkeypatch):
    fake_data = {"anonymous_customer_name": True}
    monkeypatch.setattr(orders, "_source_order_data", lambda channel: fake_data)
    channel = SimpleNamespace(
        id=123, mention="<#123>", guild=SimpleNamespace(
            get_member=lambda user_id: SimpleNamespace(display_name="老闆真名")
        )
    )
    embed = orders.build_self_service_order_embed(
        customer_mention="<@987654321012345678>",
        category_label="自訂",
        item="自訂單",
        quantity=1,
        payment_method="待付款",
        source_channel=channel,
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["顧客"] == ANONYMOUS_BOSS_LABEL
    assert fields["票口"] == "請在接單後聯繫客服取得票口"
    assert "老闆真名" not in str(embed.to_dict())
    assert "<#123>" not in str(embed.to_dict())


def test_anonymity_survives_acceptance_refresh_and_web_dispatch_contract():
    dispatch = (ROOT / "services/self_service_dispatch_runtime.py").read_text(encoding="utf-8")
    refresh = (ROOT / "services/acceptance/dispatch_refresh.py").read_text(encoding="utf-8")
    web_router = (ROOT / "web/app/routers/dispatch.py").read_text(encoding="utf-8")
    web_template = (ROOT / "web/app/templates/dispatch.html").read_text(encoding="utf-8")
    web_state = (ROOT / "web/app/routers/dispatch_state.py").read_text(encoding="utf-8")
    assert "o.price_snapshot_json" in web_state
    assert "customer_name_is_anonymous_in_snapshot" in web_state
    assert '"anonymous_customer_name": data.get("anonymous_customer_name") is True' in dispatch
    assert 'web_price_data.get("anonymous_customer_name") is True' in refresh
    assert "customer_name_is_anonymous_in_snapshot" in web_router
    assert "order.dispatch_customer_display_name" in web_template
    assert '{{ order.customer_display_name' not in web_template
    assert "customer_display_name=getattr(customer_member" in dispatch  # private identity retained
