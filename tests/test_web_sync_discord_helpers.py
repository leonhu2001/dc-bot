import asyncio

import discord
import pytest

from services.web_sync import discord_helpers


def test_normalize_dispatch_embed_field_order_preserves_panel_format():
    embed = discord.Embed(title="派單")
    embed.add_field(name="其他", value="extra", inline=True)
    embed.add_field(name="目前狀態", value="等待", inline=True)
    embed.add_field(name="數量", value="2", inline=False)
    embed.add_field(name="目前接單", value="", inline=True)
    embed.add_field(name="訂單項目", value="護航", inline=False)
    embed.add_field(name="訂單類別", value="三角洲", inline=False)

    result = discord_helpers.normalize_dispatch_embed_field_order(embed)

    assert result is embed
    assert [field.name for field in embed.fields] == [
        "訂單類別",
        "訂單項目",
        "數量",
        "接單人員",
        "接單狀態",
        "其他",
    ]
    assert [field.inline for field in embed.fields[:5]] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert embed.fields[3].value == "—"


def test_embed_without_receiver_fields_only_keeps_non_receiver_fields():
    embed = discord.Embed(title="派單")
    for name in [
        "下單用戶",
        "目前接單",
        "接單人員",
        "接單狀態",
        "打手接單",
        "陪玩接單",
        "已接人員",
        "訂單項目",
    ]:
        embed.add_field(name=name, value=name, inline=False)

    result = discord_helpers.embed_without_receiver_fields(embed)

    assert result is embed
    assert [field.name for field in embed.fields] == [
        "下單用戶",
        "訂單項目",
    ]


class _FakeGuild:
    def __init__(
        self,
        *,
        cached_member=None,
        fetched_member=None,
        cached_channel=None,
        fetched_channel=None,
        text_channels=None,
        member_error=None,
        channel_error=None,
    ):
        self.cached_member = cached_member
        self.fetched_member = fetched_member
        self.cached_channel = cached_channel
        self.fetched_channel = fetched_channel
        self.text_channels = list(text_channels or [])
        self.member_error = member_error
        self.channel_error = channel_error
        self.member_fetches = []
        self.channel_fetches = []

    def get_member(self, member_id):
        return self.cached_member

    async def fetch_member(self, member_id):
        self.member_fetches.append(member_id)
        if self.member_error is not None:
            raise self.member_error
        return self.fetched_member

    def get_channel(self, channel_id):
        return self.cached_channel

    async def fetch_channel(self, channel_id):
        self.channel_fetches.append(channel_id)
        if self.channel_error is not None:
            raise self.channel_error
        return self.fetched_channel


def test_get_member_prefers_cache_then_fetches():
    cached = object()
    guild = _FakeGuild(cached_member=cached)

    assert asyncio.run(discord_helpers.get_member(guild, 101)) is cached
    assert guild.member_fetches == []

    fetched = object()
    guild = _FakeGuild(fetched_member=fetched)

    assert asyncio.run(discord_helpers.get_member(guild, 202)) is fetched
    assert guild.member_fetches == [202]


def test_get_member_wraps_fetch_failure():
    guild = _FakeGuild(member_error=ValueError("missing"))

    with pytest.raises(
        RuntimeError,
        match="找不到網站下單顧客 Discord 成員：303",
    ):
        asyncio.run(discord_helpers.get_member(guild, 303))


def test_get_channel_uses_cache_fetch_and_invalid_fallback():
    cached = object()
    guild = _FakeGuild(cached_channel=cached)

    assert asyncio.run(discord_helpers.get_channel(guild, "11")) is cached
    assert guild.channel_fetches == []

    fetched = object()
    guild = _FakeGuild(fetched_channel=fetched)

    assert asyncio.run(discord_helpers.get_channel(guild, "22")) is fetched
    assert guild.channel_fetches == [22]

    guild = _FakeGuild(channel_error=ValueError("missing"))
    assert asyncio.run(discord_helpers.get_channel(guild, "not-an-id")) is None
    assert asyncio.run(discord_helpers.get_channel(guild, "33")) is None


class _TopicChannel:
    def __init__(self, topic):
        self.topic = topic


def test_find_ticket_falls_back_to_topic_marker():
    expected = _TopicChannel("order_customer_id=1;web_order_id=77")
    guild = _FakeGuild(
        channel_error=ValueError("missing"),
        text_channels=[
            _TopicChannel("web_order_id=12"),
            expected,
        ],
    )

    found = asyncio.run(
        discord_helpers.find_ticket(
            guild,
            77,
            stored_channel_id="999",
        )
    )

    assert found is expected


class _HistoryMessage:
    def __init__(self, embeds):
        self.embeds = embeds


class _HistoryChannel:
    def __init__(self, messages):
        self.messages = list(messages)
        self.requested_limits = []

    def history(self, *, limit):
        self.requested_limits.append(limit)

        async def _iterate():
            for message in self.messages:
                yield message

        return _iterate()


def test_has_footer_scans_recent_embeds():
    first = discord.Embed(title="one")
    first.set_footer(text="something else")

    second = discord.Embed(title="two")
    second.set_footer(text="WEB-77｜網站訂單票口")

    channel = _HistoryChannel(
        [
            _HistoryMessage([first]),
            _HistoryMessage([second]),
        ]
    )

    assert asyncio.run(
        discord_helpers.has_footer(
            channel,
            "WEB-77｜網站訂單票口",
            limit=10,
        )
    )
    assert channel.requested_limits == [10]
