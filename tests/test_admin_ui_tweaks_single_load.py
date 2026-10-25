from __future__ import annotations

from pathlib import Path


TEMPLATES = Path("web/app/templates")
UI_TWEAKS = "/static/js/ui_tweaks.js"


def test_admin_ui_tweaks_has_one_owner_per_admin_shell() -> None:
    admin = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    admin_layout = (TEMPLATES / "admin_layout.html").read_text(encoding="utf-8")
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")

    # /admin is a standalone document and does not extend admin_layout.html.
    # It must own ui_tweaks itself so report-status decoration stays available.
    assert admin.count(UI_TWEAKS) == 1

    # Layout-backed admin pages share the layout owner instead.
    assert admin_layout.count(UI_TWEAKS) == 1

    # The shared sidebar must never own executable page behavior; otherwise a
    # page that already has an owner can load the same listeners twice.
    assert UI_TWEAKS not in sidebar


def test_standalone_admin_sidebar_pages_do_not_lose_ui_tweaks() -> None:
    standalone_sidebar_pages: list[str] = []

    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if '_admin_sidebar.html' not in text:
            continue
        if path.name in {"_admin_sidebar.html", "admin_layout.html"}:
            continue

        # A page extending admin_layout receives the script from that layout.
        if 'extends "admin_layout.html"' in text or "extends 'admin_layout.html'" in text:
            continue

        standalone_sidebar_pages.append(path.name)
        assert text.count(UI_TWEAKS) == 1, (
            f"{path.name} includes the admin sidebar without admin_layout.html "
            "and must own ui_tweaks exactly once"
        )

    assert "admin.html" in standalone_sidebar_pages
