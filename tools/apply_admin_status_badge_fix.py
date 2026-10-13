from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "web/app/templates/admin.html"
TEST = ROOT / "tests/test_admin_order_status_badges.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match, found {count}: {old!r}")
    return text.replace(old, new, 1)


text = TEMPLATE.read_text(encoding="utf-8")
text = replace_once(
    text,
    '<link rel="stylesheet" href="/static/css/mw_portal_r5.css?v=admin_source_20261004_1">',
    '<link rel="stylesheet" href="/static/css/mw_portal_r5.css?v=admin_source_20261004_1">\n<link rel="stylesheet" href="/static/css/admin_order_status.css?v=20261013_1">',
)
text = replace_once(
    text,
    '''                            class="\n                                badge\n                                {{ order.status_class }}\n                            "\n                        >\n                            {{ order.status_label }}\n                        </span>''',
    '''                            class="\n                                badge\n                                admin-order-status-badge\n                                {% if order.status == "stored" %}stored{% else %}{{ order.status_class }}{% endif %}\n                            "\n                        >\n                            {% if order.status == "stored" %}已暫存{% else %}{{ order.status_label }}{% endif %}\n                        </span>''',
)
TEMPLATE.write_text(text, encoding="utf-8")

TEST.write_text(
    '''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nTEMPLATE = ROOT / "web/app/templates/admin.html"\nCSS = ROOT / "web/app/static/css/admin_order_status.css"\n\n\ndef test_admin_order_overview_loads_dedicated_status_stylesheet():\n    source = TEMPLATE.read_text(encoding="utf-8")\n    assert "/static/css/admin_order_status.css?v=20261013_1" in source\n    assert "admin-order-status-badge" in source\n\n\ndef test_admin_order_overview_localizes_stored_state():\n    source = TEMPLATE.read_text(encoding="utf-8")\n    assert 'order.status == "stored"' in source\n    assert "已暫存" in source\n\n\ndef test_admin_order_and_report_badges_have_scoped_visual_states():\n    css = CSS.read_text(encoding="utf-8")\n    assert ".order-status-col .admin-order-status-badge" in css\n    assert ".admin-order-status-badge.active" in css\n    assert ".admin-order-status-badge.done" in css\n    assert ".admin-order-status-badge.stored" in css\n    assert ".admin-order-status-badge.cancelled" in css\n    assert '.history-report-state-badge[data-status="missing"]' in css\n    assert '.history-report-state-badge[data-status="pending"]' in css\n    assert '.history-report-state-badge[data-status="changes_requested"]' in css\n    assert '.history-report-state-badge[data-status="approved"]' in css\n    assert "font-size: 13px !important" in css\n    assert "border-radius: 999px" in css\n\n\ndef test_admin_status_badge_change_does_not_touch_order_runtime_assets():\n    source = TEMPLATE.read_text(encoding="utf-8")\n    assert "mw_order.js" not in source\n    assert "mw_order_guard.js" not in source\n    assert "mw_order_quote.js" not in source\n''',
    encoding="utf-8",
)

print("admin status badge patch applied")
