from pathlib import Path


def test_public_order_dialog_does_not_render_internal_dispatch_fields():
    template = Path("web/app/templates/order_catalog.html").read_text(encoding="utf-8")
    script = Path("web/app/static/js/mw_order.js").read_text(encoding="utf-8")

    internal_ids = (
        "mw-roles",
        "mw-required-staff",
        "mw-specify",
        "mw-rule-key",
    )

    for element_id in internal_ids:
        assert f'id="{element_id}"' not in template
        assert f'getElementById(\n            "{element_id}"' not in script

    assert 'class="order3-info"' not in template
    assert 'class="order3-debug"' not in template
    assert "可接人員" not in template
    assert "需要人員" not in template


def test_public_order_catalog_has_no_generic_description_fallback():
    source = Path("web/app/services/order_groups.py").read_text(encoding="utf-8")
    assert '"選擇適合你的方案。"' not in source


def test_public_catalog_only_renders_description_when_present():
    template = Path("web/app/templates/order_catalog.html").read_text(encoding="utf-8")
    assert "{% if group.description %}" in template
