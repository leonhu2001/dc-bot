from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"


def test_templates_do_not_use_style_attributes():
    offenders = []
    pattern = re.compile(r"\bstyle\s*=", re.IGNORECASE)
    for path in TEMPLATES.rglob("*.html"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_csp_disallows_style_attributes_and_assets_are_external():
    security = (ROOT / "web/app/services/http_security.py").read_text(encoding="utf-8")
    assert "style-src-attr 'none'" in security
    assert "style-src-attr 'unsafe-inline'" not in security

    for layout_name in ("layout.html", "site_layout.html"):
        layout = (TEMPLATES / layout_name).read_text(encoding="utf-8")
        assert "/static/css/csp_style_attrs.css" in layout
        assert "/static/js/csp_dynamic_styles.js" in layout


def test_dynamic_style_bridge_uses_csp_safe_property_updates():
    source = (ROOT / "web/app/static/js/csp_dynamic_styles.js").read_text(encoding="utf-8")
    assert ".style.width" in source
    assert '.style.setProperty("--share"' in source
    assert "style.cssText" not in source
    assert 'setAttribute("style"' not in source
