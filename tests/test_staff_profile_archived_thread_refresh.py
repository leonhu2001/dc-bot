import asyncio

import discord

from views import staff_profiles


class _FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _FakeThread:
    def __init__(self, *, archived: bool):
        self.archived = archived
        self.edit_calls = []
        self.message = _FakeMessage()

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        if "archived" in kwargs:
            self.archived = bool(kwargs["archived"])
        return self

    async def fetch_message(self, message_id):
        assert int(message_id) == 456
        return self.message


class _FakeGuild:
    def __init__(self, thread):
        self.thread = thread

    def get_thread(self, channel_id):
        assert int(channel_id) == 123
        return self.thread

    def get_channel(self, channel_id):
        raise AssertionError("get_channel should not be needed when get_thread succeeds")


PROFILE = {
    "staff_discord_id": "999",
    "display_name": "Tester",
    "profile_type": "陪玩",
    "forum_thread_id": "123",
    "forum_channel_id": "321",
    "panel_message_id": "456",
}


def _patch_profile_rendering(monkeypatch):
    monkeypatch.setattr(staff_profiles, "get_staff_profile", lambda _staff_id: dict(PROFILE))
    monkeypatch.setattr(
        staff_profiles,
        "build_staff_profile_embed",
        lambda _profile: discord.Embed(title="profile"),
    )


def test_archived_public_profile_thread_stays_archived_during_background_refresh(monkeypatch):
    _patch_profile_rendering(monkeypatch)
    thread = _FakeThread(archived=True)

    refreshed = asyncio.run(
        staff_profiles.refresh_staff_profile_panel_for_staff(
            _FakeGuild(thread),
            "999",
            reason="favorite_changed",
        )
    )

    assert refreshed is True
    assert [call["archived"] for call in thread.edit_calls] == [False]
    assert thread.archived is False
    assert len(thread.message.edits) == 1


def test_active_profile_thread_is_not_reopened_again(monkeypatch):
    _patch_profile_rendering(monkeypatch)
    thread = _FakeThread(archived=False)

    refreshed = asyncio.run(
        staff_profiles.refresh_staff_profile_panel_for_staff(
            _FakeGuild(thread),
            "999",
            reason="favorite_changed",
        )
    )

    assert refreshed is True
    assert thread.edit_calls == []
    assert thread.archived is False
    assert len(thread.message.edits) == 1
