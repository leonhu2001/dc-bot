from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from web.app.services.market_health import check_market_health


class _Repository:
    def __init__(self, items=(), error: Exception | None = None):
        self.items = tuple(items)
        self.error = error

    def list_latest(self, game_key: str, *, limit: int = 200):
        assert game_key == "delta_force"
        assert limit == 500
        if self.error is not None:
            raise self.error
        return self.items


def _item(updated_at: datetime):
    return SimpleNamespace(
        source_name="852941-tw-public",
        source_updated_at=updated_at,
    )


def test_market_health_ready_reports_fresh_snapshot(monkeypatch):
    now = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)
    repo = _Repository((_item(now - timedelta(minutes=10)),) * 86)
    monkeypatch.setattr("web.app.services.market_health.configured_provider_name", lambda: "852941-tw")
    monkeypatch.setattr("web.app.services.market_health.get_market_repository", lambda: repo)
    monkeypatch.setattr(
        "web.app.services.market_health.get_web_push_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setenv("MARKET_STALE_SECONDS", "2700")

    status = check_market_health(now=now)

    assert status.ok is True
    assert status.status == "ready"
    assert status.database is True
    assert status.provider == "852941-tw"
    assert status.source_name == "852941-tw-public"
    assert status.item_count == 86
    assert status.age_seconds == 600
    assert status.web_push_enabled is True
    assert status.as_dict()["service"] == "market"


def test_market_health_marks_old_snapshot_stale(monkeypatch):
    now = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)
    repo = _Repository((_item(now - timedelta(minutes=46)),))
    monkeypatch.setattr("web.app.services.market_health.configured_provider_name", lambda: "852941-tw")
    monkeypatch.setattr("web.app.services.market_health.get_market_repository", lambda: repo)
    monkeypatch.setattr(
        "web.app.services.market_health.get_web_push_config",
        lambda: SimpleNamespace(enabled=False),
    )
    monkeypatch.setenv("MARKET_STALE_SECONDS", "2700")

    status = check_market_health(now=now)

    assert status.ok is False
    assert status.status == "stale"
    assert status.age_seconds == 2760
    assert status.web_push_enabled is False


def test_market_health_reports_unconfigured_without_touching_database(monkeypatch):
    monkeypatch.setattr("web.app.services.market_health.configured_provider_name", lambda: "")
    monkeypatch.setattr("web.app.services.market_health.get_market_repository", lambda: None)
    monkeypatch.setattr(
        "web.app.services.market_health.get_web_push_config",
        lambda: SimpleNamespace(enabled=False),
    )

    status = check_market_health()

    assert status.ok is False
    assert status.status == "unconfigured"
    assert status.configured is False
    assert status.database is False
    assert status.item_count == 0


def test_market_health_database_error_is_sanitized(monkeypatch):
    repo = _Repository(error=RuntimeError("postgres secret details"))
    monkeypatch.setattr("web.app.services.market_health.configured_provider_name", lambda: "852941-tw")
    monkeypatch.setattr("web.app.services.market_health.get_market_repository", lambda: repo)
    monkeypatch.setattr(
        "web.app.services.market_health.get_web_push_config",
        lambda: SimpleNamespace(enabled=True),
    )

    status = check_market_health()

    assert status.ok is False
    assert status.status == "database_error"
    assert status.database is False
    assert "secret" not in status.message


def test_market_health_repository_initialization_error_is_sanitized(monkeypatch):
    monkeypatch.setattr("web.app.services.market_health.configured_provider_name", lambda: "852941-tw")

    def fail_repository():
        raise RuntimeError("postgres password leak")

    monkeypatch.setattr("web.app.services.market_health.get_market_repository", fail_repository)
    monkeypatch.setattr(
        "web.app.services.market_health.get_web_push_config",
        lambda: SimpleNamespace(enabled=True),
    )

    status = check_market_health()

    assert status.ok is False
    assert status.status == "database_error"
    assert status.database is False
    assert "password" not in status.message
