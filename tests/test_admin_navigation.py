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
    layout = (TEMPLATES / "layout.html").read_text(encoding="utf-8")

    assert '_admin_backbar.html' in layout

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
    assert "/admin/search/customer/{{ row.customer_discord_id }}" in center

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


def test_legacy_duplicate_list_routes_point_to_canonical_centers():
    routers = ROOT / "web" / "app" / "routers"

    staff_source = (routers / "admin_staff.py").read_text(encoding="utf-8")
    ticket_source = (routers / "ticket_archives.py").read_text(encoding="utf-8")
    topup_source = (routers / "topups.py").read_text(encoding="utf-8")
    system_source = (routers / "admin_system.py").read_text(encoding="utf-8")

    assert "/admin/staff-center?" in staff_source
    assert "/admin/customer-center?" in staff_source
    assert 'target = f"/admin/search/customer/{customer_id}"' in staff_source
    assert 'target = "/admin/support-center"' in ticket_source
    assert 'target = "/admin/payment-reviews"' in topup_source
    assert 'url=f"/admin/anomalies?days=' in system_source


def test_system_maintenance_contains_operations_monitoring():
    page = (TEMPLATES / "admin_anomalies.html").read_text(encoding="utf-8")

    assert "營運監控" in page
    assert "智慧派單填滿率" in page
    assert "取消率" in page


def test_nested_drilldowns_preserve_return_destination():
    order_page = (TEMPLATES / "admin_order_detail.html").read_text(
        encoding="utf-8"
    )
    wallet_page = (TEMPLATES / "admin_wallet_detail.html").read_text(
        encoding="utf-8"
    )
    customer_360 = (TEMPLATES / "admin_customer_360.html").read_text(
        encoding="utf-8"
    )
    routers = ROOT / "web" / "app" / "routers"
    admin_source = (routers / "admin.py").read_text(encoding="utf-8")
    search_source = (routers / "admin_global_search.py").read_text(
        encoding="utf-8"
    )

    assert "request.query_params.get('return_to', '') | urlencode" in order_page
    assert 'name="return_to"' in wallet_page
    assert "request: Request | None = None" in admin_source
    assert 'params["return_to"] = return_to' in admin_source
    assert "child_return_param" in customer_360
    assert "child_return_param" in search_source





def test_primary_admin_workspaces_do_not_repeat_page_headers():
    dashboard = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    order = (TEMPLATES / "admin_order_detail.html").read_text(encoding="utf-8")
    staff = (TEMPLATES / "admin_staff_detail.html").read_text(encoding="utf-8")

    assert '<header class="top">' not in dashboard
    assert '<header class="top">' not in order
    assert '<div class="k">STAFF WORKSPACE</div>' not in staff
    assert "mw-admin-inline-actions" in order


def test_admin_uses_canonical_portal_css_without_overlay_theme():
    layout = (TEMPLATES / "layout.html").read_text(encoding="utf-8")
    static_css = ROOT / "web" / "app" / "static" / "css"

    assert "mw_portal_r5.css" in layout
    assert "mw_admin_theme.css" not in layout
    assert not (static_css / "mw_admin_theme.css").exists()
    assert "mw-r5-admin" in layout


def test_standalone_admin_templates_do_not_load_overlay_css():
    for path in sorted(TEMPLATES.glob("admin*.html")):
        text = path.read_text(encoding="utf-8")
        uses_layout = "extends" in text and "layout.html" in text
        includes_sidebar = "_admin_sidebar.html" in text

        assert "mw_admin_theme.css" not in text, (
            f"{path.name} still references the removed overlay theme"
        )

        if includes_sidebar and not uses_layout:
            assert "mw_portal_r5.css" in text, (
                f"{path.name} is missing canonical portal CSS"
            )


def test_portal_css_owns_admin_visual_tokens():
    portal = (
        ROOT / "web" / "app" / "static" / "css" / "mw_portal_r5.css"
    ).read_text(encoding="utf-8")

    for token in (
        "--r5-bg",
        "--r5-panel",
        "--r5-panel-3",
        "--r5-line",
        "--r5-line-strong",
        "--r5-text",
        "--r5-text-soft",
        "--r5-muted",
        "--r5-gold",
        "--r5-side",
        "--r5-font",
    ):
        assert token in portal

    assert ".mw-admin-searchbar" in portal
    assert ".mw-admin-backbar" in portal
    assert ".pay-review-page" in portal
    assert ".wallet-page" in portal
    assert ".staff-summary-page" in portal
    assert ".td-page" in portal
    assert ".ops-report" in portal


def test_core_admin_pages_no_longer_embed_visual_override_blocks():
    for filename in (
        "admin.html",
        "admin_order_detail.html",
        "admin_staff_detail.html",
        "admin_payment_reviews.html",
        "admin_wallets.html",
        "admin_wallet_detail.html",
        "admin_payout_summary.html",
        "admin_ticket_archive_detail.html",
        "admin_operations_report.html",
    ):
        text = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "<style>" not in text, (
            f"{filename} still embeds page-level visual CSS"
        )

def test_dashboard_has_no_literal_newline_and_support_rows_have_no_link_underline():
    dashboard = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    center = (TEMPLATES / "admin_center.html").read_text(encoding="utf-8")

    assert "\\n</head>" not in dashboard
    assert ".center-row{" in center
    assert "text-decoration:none" in center


def test_order_rule_admin_hides_legacy_categories_and_separates_role_groups():
    routers = ROOT / "web" / "app" / "routers"
    source = (routers / "admin_order_rules.py").read_text(encoding="utf-8")
    page = (TEMPLATES / "admin_order_rules.html").read_text(encoding="utf-8")

    assert 'ADMIN_HIDDEN_RULE_CATEGORIES = {"general", "basic", "fun"}' in source
    assert "game_rank_labels" in source
    assert "game_identity_labels" in source
    assert "game_rank_labels.items()" in page
    assert "game_identity_labels.items()" in page
    assert "game_role_labels.items()" not in page
    assert "<h3>接單職位</h3>" in page
    assert "<h3>階級資格</h3>" in page
    assert "<h3>遊戲身分</h3>" in page

