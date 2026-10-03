from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"


def test_admin_sidebar_is_navigation_only_and_consolidated():
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")

    for label in (
        "營運總覽",
        "人員中心",
        "客戶中心",
        "財務中心",
        "客服中心",
        "商品與規則",
        "AI 營運分析",
        "行銷漏斗",
        "系統維運",
        "返回官網",
    ):
        assert label in sidebar

    for old_standalone_href in (
        'href="/admin/staff"',
        'href="/admin/staff_profiles/"',
        'href="/admin/customers"',
        'href="/admin/payment-reviews?status=pending"',
        'href="/admin/payouts/summary"',
        'href="/admin/reviews/"',
        'href="/admin/tickets"',
        'href="/admin/support-calls"',
        'href="/admin/ai-support-knowledge"',
        'href="/admin/accounting-reconciliation"',
    ):
        assert old_standalone_href not in sidebar

    assert "返回上一層" not in sidebar
    assert "_admin_backbar.html" not in sidebar


def test_page_level_backbar_contains_contextual_parent_routes():
    backbar = (TEMPLATES / "_admin_backbar.html").read_text(encoding="utf-8")

    for parent in (
        "/admin/staff-center",
        "/admin/customer-center",
        "/admin/finance-center",
        "/admin/support-center",
        "/admin/anomalies",
        "/admin/payouts/summary",
    ):
        assert parent in backbar

    assert "返回上一層" in backbar


def test_every_admin_template_has_shared_admin_navigation():
    missing = []

    for path in sorted(TEMPLATES.glob("admin*.html")):
        text = path.read_text(encoding="utf-8")
        uses_layout = "extends" in text and "layout.html" in text
        includes_sidebar = "_admin_sidebar.html" in text

        if not (uses_layout or includes_sidebar):
            missing.append(path.name)

    assert not missing, (
        "Admin templates without shared navigation: "
        + ", ".join(missing)
    )


def test_custom_drilldown_templates_use_page_backbar():
    for filename in (
        "admin_staff_detail.html",
        "admin_staff_profile_edit_r5.html",
        "admin_staff_profiles_r5.html",
        "admin_customer_detail.html",
        "admin_order_detail.html",
    ):
        text = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "_admin_backbar.html" in text, (
            f"{filename} is missing page-level back navigation"
        )


def test_center_template_has_no_duplicate_full_list_entry_points():
    center = (TEMPLATES / "admin_center.html").read_text(encoding="utf-8")

    assert "完整人員管理" not in center
    assert "完整客戶名單" not in center
    assert "完整票口紀錄" not in center

    assert 'href="/admin/staff?return_to=/admin/staff-center"' not in center
    assert 'href="/admin/customers?return_to=/admin/customer-center"' not in center
    assert 'href="/admin/tickets?return_to=/admin/support-center"' not in center

    # These remain distinct operational tools rather than duplicate lists.
    assert "個人牆管理" in center
    assert "評價管理" in center
    assert "錢包帳本" in center
    assert "付款審核" in center
    assert "薪資結算" in center
    assert "帳務對帳" in center
    assert "客服鈴 / SLA" in center
    assert "AI 客服知識庫" in center


def test_admin_templates_compile_with_jinja():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

    env.get_template("_admin_sidebar.html")
    env.get_template("_admin_backbar.html")
    for path in sorted(TEMPLATES.glob("admin*.html")):
        env.get_template(path.name)
