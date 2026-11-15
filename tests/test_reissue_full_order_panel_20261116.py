from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from services import ticket_self_service_panel_idempotency as panel


class _FakeMessage:
    def __init__(self, identifier):
        self.id = identifier
        self.edits = []
        self.jump_url = f"https://discord.com/channels/1/77/{identifier}"

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _FakeChannel:
    def __init__(self):
        self.id = 77
        self.messages = {20: _FakeMessage(20)}
        self.sent = []
        self.fail_send = False

    async def fetch_message(self, message_id):
        return self.messages[int(message_id)]

    async def send(self, **kwargs):
        if self.fail_send:
            raise discord.HTTPException(
                SimpleNamespace(status=500, reason="server error"),
                "send failed",
            )
        result = _FakeMessage(101 + len(self.sent))
        self.messages[result.id] = result
        self.sent.append((result, kwargs))
        return result


class _View:
    def __init__(self, customer_id, channel_id, selected_category=None):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_category = selected_category


def _run(channel, selections, remember):
    async def invoke():
        return await panel.ensure_ticket_self_service_panel(
            interaction=SimpleNamespace(channel=channel, guild=SimpleNamespace()),
            customer_id=12345,
            selections=selections,
            bot_user_id=1,
            view_type=_View,
            panel_embed_builder=lambda customer, draft, guild: discord.Embed(
                title="自助下單",
                description=str(draft.get("category") or "請選類別"),
            ),
            remember_data=remember,
            fallback_embed=discord.Embed(title="fallback"),
            reissue_full_selection=True,
        )

    return asyncio.run(invoke())


def test_customer_service_reissue_sends_new_full_selector_at_bottom_and_retires_old(monkeypatch):
    monkeypatch.setattr(panel.discord, "TextChannel", _FakeChannel)
    channel = _FakeChannel()
    drafts = {
        77: {
            "customer_id": 12345,
            "self_service_panel_message_id": 20,
            "quick_order_v2": True,
            "quick_order_started_category": "farm",
            "category": "farm",
            "item_group": "賽季3x3",
            "item": "命運契約",
            "item_detail_value": "season_contract",
            "order_rule_key": "farm_season_3x3_contract",
            "quantity": 7,
            "manual_staff_amount": 3000,
            "selected_vip_monthly_benefit_id": "voucher",
            "payment_method": "wallet",
            "reorder_source_order_id": 129,
        }
    }
    saved = []
    result = _run(channel, drafts, lambda cid, data: saved.append((cid, dict(data))))

    assert result.id == 101
    assert len(channel.sent) == 1
    assert channel.messages[20].edits == [{"view": None}]
    assert channel.sent[0][1]["content"].startswith("<@12345>")
    assert channel.sent[0][1]["view"].selected_category is None
    assert drafts[77]["customer_id"] == 12345
    assert drafts[77]["reorder_source_order_id"] == 129
    assert drafts[77]["self_service_panel_message_id"] == 101
    for key in (
        "quick_order_v2", "category", "item_group", "item",
        "item_detail_value", "order_rule_key", "quantity",
        "manual_staff_amount", "selected_vip_monthly_benefit_id",
        "payment_method", "quick_order_started_category",
    ):
        assert key not in drafts[77]
    assert saved == [(77, dict(drafts[77]))]


def test_reissue_does_not_reset_any_dispatched_or_paid_draft(monkeypatch):
    monkeypatch.setattr(panel.discord, "TextChannel", _FakeChannel)
    for marker in (
        "dispatch_message_id", "web_order_id",
        "payment_message_id", "website_finance_settled",
    ):
        channel = _FakeChannel()
        current = {"customer_id": 12345, "item_group": "技術陪", marker: 123}
        drafts = {77: current}
        with pytest.raises(ValueError, match="不能清空重選"):
            _run(channel, drafts, lambda cid, draft: None)
        assert drafts[77] is current
        assert channel.sent == []


def test_failed_reissue_keeps_old_draft_and_panel(monkeypatch):
    monkeypatch.setattr(panel.discord, "TextChannel", _FakeChannel)
    channel = _FakeChannel()
    channel.fail_send = True
    old = {"customer_id": 12345, "category": "farm", "item_group": "賽季3x3", "self_service_panel_message_id": 20}
    drafts = {77: old}
    with pytest.raises(discord.HTTPException):
        _run(channel, drafts, lambda cid, data: None)
    assert drafts[77] is old
    assert channel.messages[20].edits == []


def test_reissue_is_used_by_actual_staff_confirm_not_buried_edit():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    assert "reissue_full_selection=True" in source
    assert "panel_message.jump_url" in source
    assert "已重新發送完整自助下單" in source
