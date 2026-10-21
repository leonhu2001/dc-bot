import threading

from types import SimpleNamespace

from web.app.services import public_staff_refresh


def test_public_staff_refresh_returns_before_sync_finishes():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def slow_refresh(max_age_seconds=60):
        calls.append(max_age_seconds)
        started.set()
        assert release.wait(timeout=2)
        finished.set()
        return {"refreshed": True}

    fake_service = SimpleNamespace(
        refresh_staff_members_if_stale=slow_refresh,
    )

    public_staff_refresh.clear_public_staff_refresh_state()
    public_staff_refresh.install_nonblocking_public_staff_refresh(fake_service)

    result = fake_service.refresh_staff_members_if_stale(max_age_seconds=60)

    assert result == {"refreshed": False, "scheduled": True}
    assert started.wait(timeout=1)
    assert not finished.is_set()

    # A second page hit while Discord refresh is running must not spawn another
    # worker or wait for the first one.
    second = fake_service.refresh_staff_members_if_stale(max_age_seconds=60)
    assert second["refreshed"] is False
    assert second["scheduled"] is False
    assert second["in_flight"] is True
    assert calls == [60]

    release.set()
    assert finished.wait(timeout=1)


def test_public_staff_refresh_coalesces_fresh_checks():
    completed = threading.Event()
    calls = []

    def fresh_refresh(max_age_seconds=60):
        calls.append(max_age_seconds)
        completed.set()
        return {"refreshed": False, "age_seconds": 5}

    fake_service = SimpleNamespace(
        refresh_staff_members_if_stale=fresh_refresh,
    )

    public_staff_refresh.clear_public_staff_refresh_state()
    public_staff_refresh.install_nonblocking_public_staff_refresh(fake_service)

    first = fake_service.refresh_staff_members_if_stale(max_age_seconds=60)
    assert first["scheduled"] is True
    assert completed.wait(timeout=1)

    second = fake_service.refresh_staff_members_if_stale(max_age_seconds=60)
    assert second == {"refreshed": False, "scheduled": False}
    assert calls == [60]
