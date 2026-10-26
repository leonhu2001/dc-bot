from pathlib import Path


TEMPLATES = Path("web/app/templates")
ADMIN_LAYOUT = TEMPLATES / "admin_layout.html"
SIDEBAR = TEMPLATES / "_admin_sidebar.html"


def test_all_admin_pages_use_canonical_admin_layout() -> None:
    offenders: list[str] = []
    for path in sorted(TEMPLATES.glob("admin_*.html")):
        if path.name == "admin_layout.html":
            continue
        source = path.read_text(encoding="utf-8")
        if '{% extends "admin_layout.html" %}' not in source:
            offenders.append(path.name)
    assert offenders == [], "Standalone admin pages bypass canonical layout: " + ", ".join(offenders)


def test_sidebar_is_owned_only_by_admin_layout() -> None:
    offenders: list[str] = []
    for path in sorted(TEMPLATES.glob("*.html")):
        if path == ADMIN_LAYOUT:
            continue
        source = path.read_text(encoding="utf-8")
        if '_admin_sidebar.html' in source:
            offenders.append(path.name)
    assert offenders == [], "Pages must not render the admin sidebar directly: " + ", ".join(offenders)


def test_canonical_admin_layout_exposes_page_asset_blocks() -> None:
    source = ADMIN_LAYOUT.read_text(encoding="utf-8")
    assert "{% block admin_head %}{% endblock %}" in source
    assert "{% block admin_scripts %}{% endblock %}" in source
    assert '_admin_sidebar.html' in source


def test_sidebar_partial_contains_navigation_only() -> None:
    source = SIDEBAR.read_text(encoding="utf-8")
    assert '<aside class="mw-r5-sidebar">' in source
    assert "<link " not in source
    assert "<script " not in source
