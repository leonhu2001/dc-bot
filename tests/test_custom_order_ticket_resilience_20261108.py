from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import custom_order_quick_entry as custom


def test_long_custom_order_intro_preserves_every_character_and_stays_under_discord_limit():
    intro = custom._custom_order_intro_text(
        support_mention="<@&1>",
        member_mention="<@2>",
        level_name="黑鑽魔丸",
        companion_count=4,
        game_or_service="三角洲" * 50,
        gameplay_rules="遊戲規則" * 250,
        goal_plan="主要目標" * 250,
        extra_request="補充事項" * 250,
        customer_notes="客服備註" * 250,
    )
    assert len(intro) > 2000
    chunks = custom._split_custom_order_intro_text(intro)
    assert len(chunks) >= 2
    assert all(0 < len(chunk) <= 1800 for chunk in chunks)
    assert "".join(chunks) == intro
    assert chunks[0].startswith("<@&1> <@2> 自訂單票口已建立。")


def _fake_ticket_environment(monkeypatch):
    class FakeMember:
        id = 12345
        mention = "<@12345>"
        display_name = "店內老闆"
        name = "店內老闆"

    class FakeCategory:
        pass

    class FakeTicket:
        id = 23456
        mention = "<#23456>"

        def __init__(self):
            self.sent = []
            self.delete = AsyncMock()

        async def send(self, *args, **kwargs):
            content = str(kwargs.get("content") or (args[0] if args else ""))
            if len(content) > 2000:
                raise ValueError("Discord message over 2000 characters")
            self.sent.append((args, kwargs))
            return SimpleNamespace(id=45678)

    class FakeGuild:
        default_role = object()
        me = None
        text_channels = []

        def __init__(self):
            self.ticket = FakeTicket()

        def get_channel(self, _id):
            return FakeCategory()

        def get_role(self, _id):
            return None

        async def create_text_channel(self, **_kwargs):
            return self.ticket

    monkeypatch.setattr(custom.discord, "Member", FakeMember)
    monkeypatch.setattr(custom.discord, "CategoryChannel", FakeCategory)
    monkeypatch.setattr(custom, "custom_order_level_name", lambda _id: "黑鑽魔丸")
    monkeypatch.setattr(custom, "format_customer_notes_for_ticket", lambda _id: "VIP 備註" * 250)
    guild = FakeGuild()
    interaction = SimpleNamespace(
        guild=guild,
        user=FakeMember(),
        client=SimpleNamespace(persistent_views=[]),
        edit_original_response=AsyncMock(),
    )
    return guild, interaction


def test_boss_long_custom_order_keeps_channel_and_delivers_all_requirements(monkeypatch):
    guild, interaction = _fake_ticket_environment(monkeypatch)
    send_panel = AsyncMock()
    monkeypatch.setattr(custom, "_send_custom_order_self_service_panel", send_panel)

    async def run():
        return await custom._create_custom_order_request_ticket(
            interaction,
            companion_count=4,
            game_or_service="三角洲端遊",
            gameplay_rules="玩法限制" * 160,
            goal_plan="目標條件" * 160,
            extra_request="其他需求" * 160,
        )

    ticket = asyncio.run(run())
    assert ticket is guild.ticket
    assert ticket.delete.await_count == 0
    assert send_panel.await_count == 1
    contents = [msg[1]["content"] for msg in ticket.sent]
    assert len(contents) >= 2
    assert all(len(content) <= 1800 for content in contents)
    combined = "".join(contents)
    assert "遊戲／服務內容：三角洲端遊" in combined
    assert "玩法限制" * 160 in combined
    assert "目標條件" * 160 in combined
    assert "其他需求" * 160 in combined
    assert "VIP 備註" * 250 in combined
    assert ticket.sent[0][1]["view"] is None
    assert "自訂單需求已送出" in interaction.edit_original_response.await_args.kwargs["content"]


def test_boss_ticket_is_preserved_if_order_panel_creation_fails(monkeypatch, capsys):
    guild, interaction = _fake_ticket_environment(monkeypatch)
    send_panel = AsyncMock(side_effect=RuntimeError("test panel failure"))
    monkeypatch.setattr(custom, "_send_custom_order_self_service_panel", send_panel)

    async def run():
        return await custom._create_custom_order_request_ticket(
            interaction,
            companion_count=1,
            game_or_service="三角洲端遊",
            gameplay_rules="一般玩法",
            goal_plan="測試目標",
            extra_request="",
        )

    ticket = asyncio.run(run())
    assert ticket is guild.ticket
    assert ticket.delete.await_count == 0
    assert any("票口會保留" in msg[1].get("content", "") for msg in ticket.sent)
    assert "票口已保留" in interaction.edit_original_response.await_args.kwargs["content"]
    logs = capsys.readouterr().out
    assert "stage=send_self_service_panel" in logs
    assert "ticket_id=23456" in logs
    assert "exception=RuntimeError" in logs


def test_corrupt_customer_notes_do_not_discard_custom_order_ticket(monkeypatch):
    guild, interaction = _fake_ticket_environment(monkeypatch)

    def unreadable_notes(_id):
        raise ValueError("invalid legacy VIP data")

    monkeypatch.setattr(custom, "format_customer_notes_for_ticket", unreadable_notes)
    send_panel = AsyncMock()
    monkeypatch.setattr(custom, "_send_custom_order_self_service_panel", send_panel)

    async def run():
        return await custom._create_custom_order_request_ticket(
            interaction,
            companion_count=2,
            game_or_service="其他遊戲",
            gameplay_rules="需求",
            goal_plan="目標",
            extra_request="",
        )

    ticket = asyncio.run(run())
    assert ticket is guild.ticket
    assert ticket.delete.await_count == 0
    assert send_panel.await_count == 1
    assert "會員備註暫時無法顯示" in "".join(
        msg[1].get("content", "") for msg in ticket.sent
    )
