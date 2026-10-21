import asyncio
import time

from web.app.services import admin_role_cache


def test_admin_role_cache_reuses_normal_reads_and_forces_refresh(monkeypatch):
    calls: list[str] = []

    def fake_get_member_role_ids(user_id: str) -> list[str]:
        calls.append(user_id)
        return ["role-1", "role-2"]

    monkeypatch.setattr(admin_role_cache, "get_member_role_ids", fake_get_member_role_ids)
    admin_role_cache.clear_admin_role_cache()

    async def scenario():
        first = await admin_role_cache.get_admin_member_role_ids("42")
        second = await admin_role_cache.get_admin_member_role_ids("42")
        refreshed = await admin_role_cache.get_admin_member_role_ids(
            "42",
            force_refresh=True,
        )
        return first, second, refreshed

    first, second, refreshed = asyncio.run(scenario())

    assert first == ["role-1", "role-2"]
    assert second == first
    assert refreshed == first
    assert calls == ["42", "42"]


def test_admin_role_cache_collapses_parallel_reads(monkeypatch):
    calls: list[str] = []

    def fake_get_member_role_ids(user_id: str) -> list[str]:
        calls.append(user_id)
        time.sleep(0.03)
        return ["role-1"]

    monkeypatch.setattr(admin_role_cache, "get_member_role_ids", fake_get_member_role_ids)
    admin_role_cache.clear_admin_role_cache()

    async def scenario():
        return await asyncio.gather(
            *[
                admin_role_cache.get_admin_member_role_ids("99")
                for _ in range(5)
            ]
        )

    results = asyncio.run(scenario())

    assert results == [["role-1"]] * 5
    assert calls == ["99"]
