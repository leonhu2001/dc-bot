from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_order_rule_sidebar_hidden_items_are_actually_hidden():
    layout_css = (
        ROOT / "web/app/static/css/pages/layout.css"
    ).read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
    rule_js = (
        ROOT / "web/app/static/js/pages/admin_order_rules_inline_1.js"
    ).read_text(encoding="utf-8")

    # The sidebar filter toggles the native HTML hidden property. Component CSS
    # also declares display:block for each rule card, so hidden must remain
    # authoritative or search/status filtering looks like it does nothing.
    assert "[hidden] { display: none !important; }" in layout_css
    assert "link.hidden = !show;" in rule_js
    assert 'data-rule-filter="active"' in template
    assert 'data-rule-filter="inactive"' in template
    assert "data-rule-search" in template


def test_order_rule_preview_exposes_publish_action_and_focuses_it():
    template = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
    tweaks = (ROOT / "web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8-sig")

    assert 'data-form-kind="publish"' in template
    assert "確認發布" in template
    assert "預覽並準備發布" in tweaks
    assert "data-rule-publish-shortcut" in tweaks
    assert "scrollIntoView" in tweaks
    assert "預覽完成，可直接確認發布" in tweaks
    assert "內容已再次修改，請重新預覽後再發布" in tweaks
