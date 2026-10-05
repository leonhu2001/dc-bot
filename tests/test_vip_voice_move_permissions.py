import asyncio

import discord

from views import voice


def test_vip_owner_move_members_is_inherited():
    overwrite = voice.build_vip_owner_overwrite()

    assert overwrite.move_members is None
    assert overwrite.view_channel is True
    assert overwrite.connect is True
    assert overwrite.manage_channels is False


def test_vip_whitelist_move_members_is_inherited():
    overwrite = voice.build_vip_whitelist_overwrite()

    assert overwrite.move_members is None
    assert overwrite.view_channel is True
    assert overwrite.connect is True
    assert overwrite.manage_channels is False


def test_default_temp_voice_policy_is_unchanged():
    overwrite = voice.build_full_temp_voice_overwrite(connect=True)

    assert overwrite.move_members is False


def test_existing_vip_owner_explicit_deny_is_normalized(monkeypatch):
    class Owner:
        id = 123
        bot = False

    owner = Owner()
    existing = discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        move_members=False,
    )

    class Guild:
        def get_member(self, user_id):
            return owner if int(user_id) == owner.id else None

    class Channel:
        guild = Guild()

        def __init__(self):
            self.updated = None

        def overwrites_for(self, member):
            assert member is owner
            return existing

        async def set_permissions(self, member, *, overwrite, reason):
            assert member is owner
            self.updated = overwrite

    channel = Channel()
    monkeypatch.setattr(voice, "get_vip_room_whitelist_user_ids", lambda _owner_id: set())

    asyncio.run(voice.sync_vip_whitelist_permissions(channel, owner.id))

    assert channel.updated is not None
    assert channel.updated.move_members is None
    assert channel.updated.view_channel is True
    assert channel.updated.connect is True
