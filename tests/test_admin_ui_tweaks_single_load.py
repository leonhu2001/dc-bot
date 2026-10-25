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
    assert '_admin_sidebar.html' in admin
    assert 'extends "admin_layout.html"' not in admin
    assert admin.count(UI_TWEAKS) == 1

    # Layout-backed admin pages share the layout owner instead.
    assert admin_layout.count(UI_TWEAKS) == 1

    # The shared sidebar must never own executable page behavior; otherwise a
    # page that already has an owner can load the same listeners twice.
    assert UI_TWEAKS not in sidebar


def test_report_status_runtime_keeps_admin_dashboard_contract() -> None:
    admin = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    ui_tweaks = Path("web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8")

    # This is the specific behavior PR #458 accidentally removed from /admin.
    assert admin.count(UI_TWEAKS) == 1
    assert "/admin/order-report-statuses" in ui_tweaks
    assert "reported" in ui_tweaks
    assert "unreported" in ui_tweaks
