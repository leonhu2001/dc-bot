from __future__ import annotations

from pathlib import Path


TEMPLATES = Path("web/app/templates")


def test_admin_ui_tweaks_has_one_owner_per_admin_shell() -> None:
    admin = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    admin_layout = (TEMPLATES / "admin_layout.html").read_text(encoding="utf-8")
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")

    # /admin is a standalone document and does not extend admin_layout.html.
    # It must own ui_tweaks itself so report-status decoration stays available.
    assert admin.count("/static/js/ui_tweaks.js") == 1

    # Layout-backed admin pages share the layout owner instead.
    assert admin_layout.count("/static/js/ui_tweaks.js") == 1

    # The shared sidebar must never own executable page behavior; otherwise a
    # page that already has an owner can load the same listeners twice.
    assert "/static/js/ui_tweaks.js" not in sidebar
