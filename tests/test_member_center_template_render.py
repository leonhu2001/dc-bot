from pathlib import Path


def test_member_center_template_has_no_inline_legacy_action_grid():
    root = Path(__file__).resolve().parents[1]
    source = (root / "web/app/templates/member_center.html").read_text(encoding="utf-8")
    assert "member-quick-actions" not in source
    assert "/static/css/member_center_v2.css" in source
    assert "mc-focus-grid" in source
