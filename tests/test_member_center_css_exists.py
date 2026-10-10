from pathlib import Path


def test_member_center_v2_stylesheet_exists_and_is_responsive():
    root = Path(__file__).resolve().parents[1]
    source = (root / "web/app/static/css/member_center_v2.css").read_text(encoding="utf-8")
    assert ".mc-hero-grid" in source
    assert "@media(max-width:620px)" in source
