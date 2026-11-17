"""Mobile V9 is a real new app shell, not the V8 layout with another patch."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "web/app/templates"
STATIC = ROOT / "web/app/static"
CSS = STATIC / "css/pages/mobile_app_v9.css"
JS = STATIC / "js/pages/mobile_app_v9.js"
SHELL = TPL / "_mobile_v9_shell.html"
PAGE = TPL / "_mobile_v9_page.html"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def jinja_render(name: str, *, route: str, area: str, user=None, **extra) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TPL)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(name)
    return template.render(
        request=SimpleNamespace(url=SimpleNamespace(path=route)),
        mobile_v9_area=area, user=user, **extra,
    )


def test_v9_is_the_only_phone_chrome_in_both_layouts():
    for filename in ("site_layout.html", "admin_layout.html"):
        html = source(TPL / filename)
        assert 'mobile_app_v9.css?v=20261117-1' in html
        assert 'mobile_app_v9.js?v=20261117-1' in html
        assert 'include "_mobile_v9_shell.html"' in html
        assert 'include "_mobile_v9_page.html"' in html
        assert "m9-mobile" in html
        assert "mobile_app_unified_v8.css" not in html
        assert "mobile_app_unified_v8.js" not in html
        assert 'include "_customer_mobile_app_shell.html"' not in html
        assert 'include "_employee_mobile_app_shell.html"' not in html
        assert 'include "_admin_mobile_app_shell.html"' not in html
        assert 'href="#m8-main"' in html and 'id="m8-main"' in html
        assert html.index("mobile_app_v9.css") < html.index("</head>")
    assert "mobile_app_v9.css" not in source(TPL / "site_layout.html").split("{% if mobile_ui %}")[0]


def test_one_rail_three_role_specific_navigation_shells():
    for area, route, expected in (
        ("customer", "/", ("/order", "/vip", "/me/orders")),
        ("employee", "/dispatch", ("/employee", "/dispatch/reports", "/my/payouts")),
        ("admin", "/admin", ("/admin/customer-center", "/admin/support-center", "/admin/finance-center")),
    ):
        html = jinja_render("_mobile_v9_shell.html", route=route, area=area)
        assert 'class="m9-topbar' in html
        assert 'class="m9-dock' in html
        assert "m9-brand-name" in html
        for href in expected:
            assert f'href="{href}"' in html
        if area == "customer":
            assert 'href="/auth/discord/login"' in html
            assert "更多功能" not in html
        else:
            assert "m9-sheet-backdrop" in html
            assert "m9-more" in html
            assert 'href="/admin/order-rules"' not in html


def test_admin_manager_receives_management_routes_without_revealing_to_customer():
    manager = SimpleNamespace(
        display_name="店長", global_name=None, username="店長", avatar=None,
        is_admin=False, is_customer_service=True, is_manager=True, id=1234,
    )
    manager_html = jinja_render(
        "_mobile_v9_shell.html", route="/admin", area="admin", user=manager,
    )
    assert 'href="/admin/order-rules"' in manager_html
    assert 'href="/admin/benefits"' in manager_html
    assert 'href="/employee"' in manager_html
    employee_html = jinja_render(
        "_mobile_v9_shell.html", route="/employee", area="employee", user=manager,
    )
    assert 'href="/dispatch/reports/review"' in employee_html
    assert 'href="/employee/store-bindings"' in employee_html


@pytest.mark.parametrize("route,area,title", [
    ("/", "customer", "今晚"),
    ("/order", "customer", "選擇服務"),
    ("/staff", "customer", "陪玩陣容"),
    ("/vip", "customer", "VIP 會員"),
    ("/me/orders", "customer", "我的訂單"),
    ("/employee", "employee", "員工工作台"),
    ("/dispatch", "employee", "接單大廳"),
    ("/dispatch/reports", "employee", "報單管理"),
    ("/admin", "admin", "營運總覽"),
    ("/admin/orders/history", "admin", "魔丸娛樂"),
])
def test_mobile_v9_page_uses_route_specific_heading_and_useful_links(route,area,title):
    html = jinja_render("_mobile_v9_page.html", route=route, area=area)
    assert title in html
    assert 'class="m9-intro' in html
    if route != "/":
        assert 'class="m9-section-heading"' in html
    if route == "/":
        assert 'href="/order"' in html and 'href="/staff"' in html


def test_order_category_selection_preserves_staff_filter_without_form_changes():
    categories = [SimpleNamespace(key="delta", label="三角洲"), SimpleNamespace(key="lol", label="英雄聯盟")]
    staff = SimpleNamespace(staff_id=123, display_name="陪玩甲", avatar_url="/static/img/a.png", role_title="技術陪")
    html = jinja_render(
        "_mobile_v9_page.html", route="/order", area="customer",
        categories=categories, category_filter="delta", selected_staff=staff,
    )
    assert '/order?category=delta&amp;staff=123' in html
    assert '/order?category=lol&amp;staff=123' in html
    assert 'aria-current="page"' in html
    assert '已指定陪玩' in html


def test_v9_true_relayout_and_device_stability():
    css = source(CSS)
    for marker in (
        "--m9-rail: 560px", "--m9-top: 62px", "--m9-dock-height: 72px",
        "--m9-control-height: 48px", "--m9-card-radius: 21px",
        "safe-area-inset-bottom", "100dvh", ".m9-intro",
        ".m9-shortcuts", ".m9-card-table", ".m9-sheet",
        "grid-template-columns: repeat(5, minmax(0, 1fr))",
        "grid-template-columns: minmax(0,1fr)",
        "@media (max-width: 767px)", "@media (prefers-reduced-motion: reduce)",
        "transform: none !important;", "backdrop-filter: none !important;",
    ):
        assert marker in css
    assert 'body.m9-mobile .site-main' in css
    assert 'body.m9-mobile .mw-mobile-main-host' in css


def test_v9_js_does_not_mutate_business_state_or_intercept_native_checkout():
    script = source(JS)
    for marker in ("MutationObserver", "m9-card-table", "aria-current",
                   "aria-invalid", "scrollIntoView", "sessionStorage",
                   "pageshow", "focusin", "Escape", "prefers-reduced-motion"):
        assert marker in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "POST" in script
    assert ".preventDefault()" not in script.split("function noteNavigation")[1].split("function restoreExplicitNav")[0]


def test_dispatch_new_and_changed_only_do_not_rewrite_existing_history():
    worker = source(ROOT / "services/acceptance/sync_worker.py")
    assert "paid_dispatch_embed_reconcile_worker" not in worker
    assert "reconcile_recent_paid_dispatch_embeds" not in worker
    payment = source(ROOT / "services/order_payment_runtime.py")
    assert "unify_dispatch_embed(" in payment
    # The one-off historical reconciler may remain for a deliberate future
    # operator action, but must NOT start from the Bot event worker.
