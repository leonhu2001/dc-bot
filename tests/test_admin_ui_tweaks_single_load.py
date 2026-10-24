from __future__ import annotations

from pathlib import Path


TEMPLATES = Path("web/app/templates")


def test_admin_ui_tweaks_has_one_shell_owner() -> None:
    admin_layout = (TEMPLATES / "admin_layout.html").read_text(encoding="utf-8")
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")

    assert admin_layout.count("/static/js/ui_tweaks.js") == 1
    assert "/static/js/ui_tweaks.js" not in sidebar
