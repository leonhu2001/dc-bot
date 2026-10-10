from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_member_portal_refresh_accepts_legacy_and_hidden_markers():
    source = (ROOT / "cogs/staff_sync.py").read_text(encoding="utf-8")
    assert 'footer_text in {MEMBER_PORTAL_MARKER, "MAWAN_MEMBER_PORTAL_V1"}' in source
