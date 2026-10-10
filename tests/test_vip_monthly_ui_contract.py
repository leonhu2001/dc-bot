from pathlib import Path


def test_vip_management_is_inside_customer_center_not_sidebar():
    root = Path(__file__).resolve().parents[1]
    sidebar = (root / "web/app/templates/_admin_sidebar.html").read_text(encoding="utf-8")
    center = (root / "web/app/templates/admin_center.html").read_text(encoding="utf-8")

    assert "↳ VIP 管理" not in sidebar
    assert 'href="/admin/customer-center/vip"' in center
    assert "👑 VIP 會員管理" in center
    assert "_p.startswith('/admin/customer-center')" in sidebar


def test_member_portal_has_black_diamond_monthly_redemption_contract():
    root = Path(__file__).resolve().parents[1]
    source = (root / "views/member_portal.py").read_text(encoding="utf-8")
    customer_commands = (root / "cogs/customer_commands.py").read_text(encoding="utf-8")

    assert "黑鑽會員專屬兌換" in source
    assert "機密航天保底 1000w" in source
    assert "娛樂陪 2H" in source
    assert "reserve_black_diamond_choice" in source
    assert "release_black_diamond_choice" in source
    assert "redeem_black_diamond_choice" in source
    assert "BlackDiamondRedemptionControlView" in customer_commands
    assert "bot.add_view(BlackDiamondRedemptionControlView())" in customer_commands
