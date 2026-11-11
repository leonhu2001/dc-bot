"""Recruitment examiner permission and original support panel contracts.

Use synthetic interactions: no production Discord channels or payouts are touched.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import views.panels as panels


class FakeMember:
    id = 987654321
    display_name = "申請者"
    name = "申請者"
    mention = "<@987654321>"

    def __init__(self):
        self.add_roles = AsyncMock()


class FakeRole:
    def __init__(self, role_id):
        self.id = role_id
        self.mention = f"<@&{role_id}>"


def _configure_recruit_panel(monkeypatch, *, has_examiner):
    examiner_id = panels.RECRUIT_PANEL_EXAMINER_ROLE_ID
    assert examiner_id == 1570070903935737887
    monkeypatch.setattr(panels.discord, "Member", FakeMember)
    for name, value in (
        ("EXAM_CATEGORY_ID", 123),
        ("EXAMINER_ROLE_ID", 456),
        ("MANAGER_ROLE_ID", 456),  # live system may merge staff roles
        ("CUSTOMER_ROLE_ID", 456),
        ("RECRUIT_APPLICANT_ROLE_ID", 789),
    ):
        monkeypatch.setattr(panels, name, value)
    monkeypatch.setattr(panels, "safe_channel_name", lambda kind, member: "入職-申請者")
    creator = AsyncMock()
    monkeypatch.setattr(panels, "create_private_channel", creator)
    monkeypatch.setattr(panels, "recruit_control_view_factory", lambda: "test-view")
    roles = {456: FakeRole(456), 789: FakeRole(789)}
    if has_examiner:
        roles[examiner_id] = FakeRole(examiner_id)
    guild = SimpleNamespace(get_role=lambda role_id: roles.get(role_id))
    member = FakeMember()
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = SimpleNamespace(guild=guild, user=member, response=response)
    modal = SimpleNamespace(
        nickname=SimpleNamespace(value="小明"),
        age=SimpleNamespace(value="20"),
        play_time=SimpleNamespace(value="晚上"),
        position=SimpleNamespace(value="陪玩"),
    )
    return modal, interaction, creator


def test_recruit_button_grants_dedicated_examiner_alongside_existing_staff(monkeypatch):
    modal, interaction, creator = _configure_recruit_panel(monkeypatch, has_examiner=True)
    asyncio.run(panels.RecruitModal.on_submit(modal, interaction))
    creator.assert_awaited_once()
    payload = creator.await_args.kwargs
    assert payload["category_id"] == 123
    assert payload["channel_name"] == "入職-申請者"
    assert payload["topic"].startswith("recruit_member_id=987654321;")
    # Merged manager/customer role stays in the ticket; the dedicated examiner
    # is an ADDITIONAL role rather than a global replacement for the old role.
    assert {role.id for role in payload["allowed_roles"]} == {
        456, 1570070903935737887,
    }
    assert len(payload["allowed_roles"]) == 2
    assert payload["view"] == "test-view"
    assert interaction.user.add_roles.await_count == 1


def test_missing_recruit_examiner_fails_before_ticket_creation(monkeypatch):
    modal, interaction, creator = _configure_recruit_panel(monkeypatch, has_examiner=False)
    asyncio.run(panels.RecruitModal.on_submit(modal, interaction))
    creator.assert_not_awaited()
    interaction.user.add_roles.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    assert "考官身分組" in interaction.response.send_message.await_args.args[0]
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


def test_private_ticket_creator_grants_talk_read_history_to_allowed_roles():
    # bot.py is not importable without production credentials. Verify that the
    # actual creator receives the role list and explicitly grants each role
    # view/send/history in the channel permission overwrites.
    code = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    start = code.index("async def create_private_channel(")
    stop = code.index("    channel = await guild.create_text_channel(", start)
    ticket_access_code = code[start:stop]
    assert "for role in allowed_roles:" in ticket_access_code
    role_block = ticket_access_code[ticket_access_code.index("for role in allowed_roles:"):]
    assert "overwrites[role] = discord.PermissionOverwrite(" in role_block
    assert "view_channel=True" in role_block
    assert "send_messages=True" in role_block
    assert "read_message_history=True" in role_block
