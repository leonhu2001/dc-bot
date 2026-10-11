import asyncio
from types import SimpleNamespace

from services.vip_review_runtime import _candidate_lines


class _FakeGuild:
    def get_member(self, user_id: int):
        assert user_id == 123456789012345678
        return SimpleNamespace(display_name="金銀魔丸", name="account-name")

    async def fetch_member(self, user_id: int):
        raise AssertionError("cached member should be used before fetching")


class _FakeBot:
    guilds = [_FakeGuild()]

    def get_user(self, user_id: int):
        return None

    async def fetch_user(self, user_id: int):
        raise AssertionError("guild nickname should be used before user fallback")


def test_vip_review_candidate_list_uses_server_nickname_without_mentions_or_ids():
    rows = [
        {
            "customer_id": "123456789012345678",
            "days_overdue": 72,
            "current_level": "金級魔丸",
            "suggested_level": "銀級魔丸",
        }
    ]

    value = asyncio.run(_candidate_lines(_FakeBot(), rows))

    assert value == "金銀魔丸｜金級魔丸 → 銀級魔丸｜逾期 72 天"
    assert "<@" not in value
    assert "123456789012345678" not in value
