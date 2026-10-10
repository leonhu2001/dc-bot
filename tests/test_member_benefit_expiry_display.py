from pathlib import Path


def test_web_and_discord_show_coupon_expiry():
    root = Path(__file__).resolve().parents[1]
    web = (root / "web/app/templates/member_center.html").read_text(encoding="utf-8")
    discord = (root / "views/member_portal.py").read_text(encoding="utf-8")
    assert "有效至 {{ coupon.expires_at_text" in web
    assert "有效至 {item.get('expires_at_text')" in discord
