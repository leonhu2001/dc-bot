import asyncio

from web.app.routers import dispatch_state


def test_shared_dispatch_event_snapshot_reuses_one_db_snapshot(monkeypatch):
    calls = []

    def fake_build_snapshot():
        calls.append("build")
        return {
            "count": 1,
            "keys": ["WEB-1"],
            "signature": "1:WEB-1",
            "online_companion_count": 3,
            "online_support_count": 1,
        }

    monkeypatch.setattr(
        dispatch_state,
        "_build_dispatch_event_snapshot",
        fake_build_snapshot,
    )
    dispatch_state._dispatch_event_cache = None
    dispatch_state._dispatch_event_cache_expires_at = 0.0

    async def run_twice():
        first = await dispatch_state._shared_dispatch_event_snapshot()
        second = await dispatch_state._shared_dispatch_event_snapshot()
        return first, second

    first, second = asyncio.run(run_twice())

    assert first == second
    assert calls == ["build"]
