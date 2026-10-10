from pathlib import Path


def test_staff_sync_schedules_member_portal_after_extension_load():
    root = Path(__file__).resolve().parents[1]
    source = (root / "cogs/staff_sync.py").read_text(encoding="utf-8")
    init_pos = source.index("class StaffSyncCog")
    source = source[init_pos:]
    assert "self.member_portal_panel_task = asyncio.create_task(" in source
    assert "await self.bot.wait_until_ready()" in source
    assert "await self._ensure_member_portal_panel()" in source
