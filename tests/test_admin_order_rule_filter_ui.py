from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_order_rule_sidebar_hidden_items_are_actually_hidden():
    layout = (ROOT / "web/app/templates/layout.html").read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")

    # The sidebar filter toggles the native HTML hidden property. Component CSS
    # also declares display:block for each rule card, so hidden must remain
    # authoritative or search/status filtering looks like it does nothing.
    assert "[hidden] { display: none !important; }" in layout
    assert "link.hidden = !show;" in template
    assert 'data-rule-filter="active"' in template
    assert 'data-rule-filter="inactive"' in template
    assert "data-rule-search" in template
