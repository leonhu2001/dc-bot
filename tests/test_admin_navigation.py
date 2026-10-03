from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"


def test_admin_sidebar_is_consolidated_into_work_centers():
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

    assert "← 返回上一層" in sidebar


def test_every_admin_template_has_shared_admin_navigation():
    missing = []

    for path in sorted(TEMPLATES.glob("admin*.html")):
        text = path.read_text(encoding="utf-8")
        uses_layout = "extends" in text and "layout.html" in text
        includes_sidebar = "_admin_sidebar.html" in text

        if not (uses_layout or includes_sidebar):
            missing.append(path.name)

    assert not missing, (
        "Admin templates without shared sidebar/back navigation: "
        + ", ".join(missing)
    )


def test_known_drilldown_pages_keep_explicit_return_paths():
    expectations = {
        "admin_staff_detail.html": "/admin/staff-center",
        "admin_staff_profile_edit_r5.html": "/admin/staff-center",
        "admin_customer_detail.html": "/admin/customer-center",
        "admin_wallet_detail.html": "return_to",
        "admin_ticket_archive_detail.html": "return_to",
        "admin_order_detail.html": "return_to",
        "admin_accounting_reconciliation.html": "return_to",
        "admin_anomalies.html": "return_to",
    }

    for filename, marker in expectations.items():
        text = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert marker in text, f"{filename} is missing return navigation"


def test_admin_templates_compile_with_jinja():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

    env.get_template("_admin_sidebar.html")
    for path in sorted(TEMPLATES.glob("admin*.html")):
        env.get_template(path.name)
