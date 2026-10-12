from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tests that intentionally assert CSS/JS behavior must follow the canonical
# extracted assets instead of requiring those rules to stay inline in HTML.
path = ROOT / "tests/test_admin_navigation.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
'''    center = (TEMPLATES / "admin_center.html").read_text(encoding="utf-8")

    assert "\\\\n</head>" not in dashboard
    assert ".center-row{" in center
    assert "text-decoration:none" in center
''',
'''    center_css = (
        ROOT / "web/app/static/css/pages/admin_center_inline_1.css"
    ).read_text(encoding="utf-8")

    assert "\\\\n</head>" not in dashboard
    assert ".center-row{" in center_css
    assert "text-decoration:none" in center_css
''',
)
text = text.replace(
'''    page = (TEMPLATES / "admin_order_rules.html").read_text(encoding="utf-8")
''',
'''    page = (TEMPLATES / "admin_order_rules.html").read_text(encoding="utf-8")
    page_css = (
        ROOT / "web/app/static/css/pages/admin_order_rules_inline_1.css"
    ).read_text(encoding="utf-8")
''',
)
text = text.replace(
'''    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in page
''',
'''    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in page_css
''',
)
path.write_text(text, encoding="utf-8")

path = ROOT / "tests/test_admin_order_rule_filter_ui.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
'''    layout = (ROOT / "web/app/templates/layout.html").read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
''',
'''    layout_css = (
        ROOT / "web/app/static/css/pages/layout_inline_1.css"
    ).read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
    rule_js = (
        ROOT / "web/app/static/js/pages/admin_order_rules_inline_1.js"
    ).read_text(encoding="utf-8")
''',
)
text = text.replace(
'''    assert "[hidden] { display: none !important; }" in layout
    assert "link.hidden = !show;" in template
''',
'''    assert "[hidden] { display: none !important; }" in layout_css
    assert "link.hidden = !show;" in rule_js
''',
)
path.write_text(text, encoding="utf-8")

path = ROOT / "tests/test_order_product_status.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
'''    router = Path("web/app/routers/admin_order_rules.py").read_text(encoding="utf-8")

    assert 'id="order-rule-sidebar"' in template
''',
'''    router = Path("web/app/routers/admin_order_rules.py").read_text(encoding="utf-8")
    rule_js = Path("web/app/static/js/pages/admin_order_rules_inline_1.js").read_text(
        encoding="utf-8"
    )

    assert 'id="order-rule-sidebar"' in template
''',
)
text = text.replace(
'''    assert "尚未發布的修改" in template
    assert "fetchPage" in template
''',
'''    assert "尚未發布的修改" in rule_js
    assert "fetchPage" in rule_js
''',
)
path.write_text(text, encoding="utf-8")

print("aligned static extraction regressions")
