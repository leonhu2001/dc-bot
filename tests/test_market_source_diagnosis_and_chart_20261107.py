from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.market.poll_diagnostics import (
    load_market_poll,
    market_delay_diagnosis,
    record_market_poll,
)


ROOT = Path(__file__).resolve().parents[1]


def test_upstream_unchanged_is_not_confused_with_worker_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_POLL_STATE_FILE", str(tmp_path / "state.json"))
    now = datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)
    record_market_poll(
        game_key="delta_force",
        status="duplicate",
        provider="Public852941Provider",
        checked_at=now - timedelta(minutes=4),
    )
    state = load_market_poll()
    diagnosis = market_delay_diagnosis(
        source_updated_at=now - timedelta(hours=4),
        now=now,
        poll=state,
        expected_poll_seconds=900,
    )
    assert diagnosis["reason"] == "source_timestamp_unchanged"
    assert diagnosis["poll_age_seconds"] == 240
    assert "最近抓取成功" in diagnosis["message"]


def test_worker_stopped_and_source_error_have_different_causes(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_POLL_STATE_FILE", str(tmp_path / "state.json"))
    now = datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)
    record_market_poll(
        game_key="delta_force",
        status="source_unavailable",
        provider="Public852941Provider",
        checked_at=now - timedelta(minutes=1),
    )
    args = {"source_updated_at": now - timedelta(hours=4), "now": now}
    assert market_delay_diagnosis(**args, poll=load_market_poll())["reason"] == "upstream_fetch_failed"
    record_market_poll(
        game_key="delta_force",
        status="stored",
        provider="Public852941Provider",
        checked_at=now - timedelta(hours=2),
    )
    assert market_delay_diagnosis(**args, poll=load_market_poll())["reason"] == "worker_not_polling"
    assert market_delay_diagnosis(**args, poll=None)["reason"] == "no_poll_record"


def test_public_diagnostics_do_not_record_exception_messages_or_secrets(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("MARKET_POLL_STATE_FILE", str(state_path))
    record_market_poll(game_key="delta_force", status="error", provider="test")
    state = state_path.read_text(encoding="utf-8")
    assert "error" in state
    assert "password" not in state


def test_chart_has_hover_tooltips_time_presets_and_draggable_brush():
    template = (ROOT / "web/app/templates/game_market_item.html").read_text(encoding="utf-8")
    js = (ROOT / "web/app/static/js/pages/game_market_item.js").read_text(encoding="utf-8")
    css = (ROOT / "web/app/static/css/pages/game_market_item.css").read_text(encoding="utf-8")
    for hours in (0, 12, 24, 72, 168, 720):
        assert f'data-market-range="{hours}"' in template
    for marker in ("data-market-chart-tooltip", "data-market-navigator", "data-market-nav-window",
                   'data-market-nav-handle="start"', 'data-market-nav-handle="end"'):
        assert marker in template
    for marker in ("focusPoint", "pointermove", "pointerdown", "setPointerCapture",
                   "releasePointerCapture", "keydown", "renderChartSelection", "renderNavigator"):
        assert marker in js
    assert ".market-item-chart-nav-handle" in css
    assert ".market-item-chart-tooltip" in css


def test_market_health_and_web_page_report_delay_cause():
    health = (ROOT / "web/app/services/market_health.py").read_text(encoding="utf-8")
    worker = (ROOT / "services/market/worker.py").read_text(encoding="utf-8")
    snapshot = (ROOT / "services/market/public_snapshot.py").read_text(encoding="utf-8")
    for marker in ("delay_reason", "poll_age_seconds", "last_poll_at", "market_delay_diagnosis"):
        assert marker in health
    assert "record_market_poll" in worker
    assert "market_delay_diagnosis" in snapshot
