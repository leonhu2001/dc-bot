from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_staff_profile_sync_is_change_driven_not_periodic_full_refresh():
    source = _read("cogs/staff_sync.py")

    assert "claim_staff_profile_refresh_events" in source
    assert "staff_profile_refresh_event_loop" in source
    assert "staff_profile_reconcile_loop" not in source
    assert "get_staff_profile_panel_rows" not in source


def test_companion_presence_channel_only_manages_the_dynamic_name():
    source = _read("views/dispatch_presence.py")

    assert "format_dispatch_presence_channel_name" in source
    assert "channel.edit(" in source
    assert "set_permissions" not in source
    assert "PermissionOverwrite" not in source
