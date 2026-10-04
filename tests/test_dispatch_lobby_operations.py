from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dispatch_lobby_has_operational_sections_and_realtime_controls():
    template = _read("web/app/templates/dispatch.html")

    assert "還缺 {{ order.dispatch_missing_staff_count }} 人" in template
    assert "可接任務" in template
    assert "進行中／已滿任務" in template
    assert "data-dispatch-realtime-status" in template
    assert "data-dispatch-last-sync" in template
    assert "data-dispatch-notification-toggle" in template
    assert "前往票口" in template
    assert 'data-busy-label="接單中…"' in template


def test_dispatch_alert_client_updates_on_state_changes_without_full_reload():
    script = _read("web/app/static/js/dispatch_alerts.js")

    assert "new Notification('魔丸娛樂｜有新單'" in script
    assert "document.title = '🔔 有新單｜接單大廳'" in script
    assert "order state changed, refreshing silently" in script
    assert "currentShell.replaceWith(nextShell)" in script
    assert "window.location.reload" not in script
    assert "form.dataset.dispatchSubmitting === '1'" in script


def test_companion_presence_channel_uses_new_canonical_id():
    bot_source = _read("bot.py")

    assert "DISPATCH_ONLINE_CHANNEL_ID = 1556366139830042634" in bot_source
    assert "DISPATCH_ONLINE_CHANNEL_ID = 1483183532330455040" not in bot_source


def test_online_companion_label_uses_same_inline_text_style():
    template = _read("web/app/templates/dispatch.html")
    script = _read("web/app/static/js/dispatch_alerts.js")

    assert "在線陪玩：{{ online_companion_count }}" in template
    assert "'在線陪玩：' + onlineCompanionCount" in script
    assert "🟢 在線陪玩 {{ online_companion_count }} 人" not in template
