import asyncio

from views import smart_dispatch


def test_smart_dispatch_restores_three_fixed_public_rounds():
    assert smart_dispatch.PUBLIC_ACCEPTANCE_OPEN_SECONDS == 60
    assert smart_dispatch.SECOND_WAVE_SECONDS == 240
    assert smart_dispatch.FULL_EXPANSION_SECONDS == 420
    assert smart_dispatch.REPEAT_REMINDER_SECONDS == 600


def test_initial_locked_alert_is_immediate_and_has_no_mentions():
    sent = {}

    class Channel:
        async def send(self, content, **kwargs):
            sent["content"] = content
            sent.update(kwargs)
            return object()

    class Guild:
        def get_channel(self, channel_id):
            assert channel_id == smart_dispatch.SMART_DISPATCH_ALERT_CHANNEL_ID
            return Channel()

    result = asyncio.run(
        smart_dispatch.send_initial_smart_dispatch_alert(
            Guild(),
            content="<@123> should never be forwarded",
            dispatch_jump_url="https://discord.com/channels/1/2/3",
        )
    )

    assert result is not None
    assert "新單已建立｜1 分鐘接單保護期" in sent["content"]
    assert "指定人員若符合訂單資格，可立即接單" in sent["content"]
    assert "<@" not in sent["content"]
    assert sent["allowed_mentions"].users is False
    assert sent["allowed_mentions"].roles is False
    assert sent["allowed_mentions"].everyone is False
