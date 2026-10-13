from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "web/app/templates/admin.html"
CSS = ROOT / "web/app/static/css/admin_order_status.css"


def test_admin_order_overview_loads_dedicated_status_stylesheet():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "/static/css/admin_order_status.css?v=20261013_1" in source
    assert "admin-order-status-badge" in source


def test_admin_order_overview_localizes_stored_state():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'order.status == "stored"' in source
    assert "已暫存" in source


def test_admin_order_and_report_badges_have_scoped_visual_states():
    css = CSS.read_text(encoding="utf-8")
    assert ".order-status-col .admin-order-status-badge" in css
    assert ".admin-order-status-badge.active" in css
    assert ".admin-order-status-badge.done" in css
    assert ".admin-order-status-badge.stored" in css
    assert ".admin-order-status-badge.cancelled" in css
    assert '.history-report-state-badge[data-status="missing"]' in css
    assert '.history-report-state-badge[data-status="pending"]' in css
    assert '.history-report-state-badge[data-status="changes_requested"]' in css
    assert '.history-report-state-badge[data-status="approved"]' in css
    assert "font-size: 13px !important" in css
    assert "border-radius: 999px" in css


def test_admin_status_badge_change_does_not_touch_order_runtime_assets():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "mw_order.js" not in source
    assert "mw_order_guard.js" not in source
    assert "mw_order_quote.js" not in source
