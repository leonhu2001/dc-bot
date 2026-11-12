"""The legacy staff '派單' button may never duplicate an existing quick order panel."""
import asyncio
from types import SimpleNamespace

import discord

from services.self_service_panel_dedupe import (
    _is_self_service_panel,ensure_single_self_service_panel,
)


class FakePanelMessage:
    def __init__(self, *, title="自助下單", owner=99, message_id=1):
        self.id=message_id
        self.author=SimpleNamespace(id=owner)
        self.embeds=[SimpleNamespace(title=title)]
        self.components=[SimpleNamespace(children=[
            SimpleNamespace(custom_id="self_service_order_detail_select")
        ])]


class FakeChannel:
    def __init__(self, initial=()):
        self.id=1234567
        self.guild=SimpleNamespace(me=SimpleNamespace(id=99))
        self.messages=list(initial)
        self.sent=0

    def history(self, limit):
        async def iterable():
            for message in reversed(self.messages[-limit:]):
                yield message
        return iterable()

    async def send(self, **kwargs):
        self.sent+=1
        message=FakePanelMessage(message_id=100+self.sent)
        self.messages.append(message)
        return message


def view_factory(**kwargs):
    assert kwargs=={"customer_id":23,"channel_id":1234567}
    return "fake-view"


def _ensure(channel):
    return ensure_single_self_service_panel(
        channel,customer_id=23,embed=discord.Embed(title="自助下單"),
        view_factory=view_factory,
    )


def test_quick_ticket_existing_panel_is_reused_no_second_message():
    channel=FakeChannel([FakePanelMessage()])
    message,created=asyncio.run(_ensure(channel))
    assert not created and message.id==1
    assert channel.sent==0


def test_legacy_ticket_creates_only_once_on_repeated_staff_actions():
    channel=FakeChannel()
    async def check():
        first=await _ensure(channel)
        second=await _ensure(channel)
        return first,second
    (first,second)=asyncio.run(check())
    assert first[1] is True and second[1] is False
    assert first[0] is second[0]
    assert channel.sent==1


def test_two_staff_clicks_racing_are_serialized_for_same_ticket():
    channel=FakeChannel()
    async def check():
        return await asyncio.gather(_ensure(channel),_ensure(channel))
    results=asyncio.run(check())
    assert channel.sent==1
    assert {flag for _,flag in results}=={True,False}
    assert results[0][0] is results[1][0]


def test_other_user_and_non_self_service_embed_not_mistaken_for_panel():
    false_panel=FakePanelMessage(title="歡迎訊息",owner=99)
    wrong_owner=FakePanelMessage(title="自助下單",owner=123)
    assert not _is_self_service_panel(false_panel,bot_id=99)
    assert not _is_self_service_panel(wrong_owner,bot_id=99)


def test_legacy_dispatch_button_uses_dedupe_not_unconditional_send():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/"bot.py").read_text(encoding="utf-8")
    start=source.index("class OrderControlView(")
    end=source.index("# profile_direct_order_ticket_creator_v1",start)
    block=source[start:end]
    assert "handle_legacy_order_control_dispatch(" in block
    assert 'await interaction.channel.send(' not in block
    helper=(Path(__file__).resolve().parents[1]/"services/self_service_panel_dedupe.py").read_text(encoding="utf-8")
    assert "ensure_single_self_service_panel(" in helper
    assert "票口已有自助下單面板" in helper
