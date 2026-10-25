from __future__ import annotations

from pathlib import Path


TEMPLATES = Path("web/app/templates")
UI_TWEAKS = "/static/js/ui_tweaks.js"


def test_admin_ui_tweaks_has_one_owner_per_admin_shell() -> None:
    admin = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    admin_layout = (TEMPLATES / "admin_layout.html").read_text(encoding="utf-8")
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")

    # /admin now intentionally uses the same document shell as every other
    # customer-service page. The layout is the single runtime owner.
    assert '{% extends "admin_layout.html" %}' in admin
    assert UI_TWEAKS not in admin
    assert admin_layout.count(UI_TWEAKS) == 1

    # Shared partials must never own executable page behavior; otherwise a
    # layout-backed page can load the same listeners twice.
    assert UI_TWEAKS not in sidebar


def test_report_status_runtime_keeps_admin_dashboard_contract() -> None:
    admin = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    admin_layout = (TEMPLATES / "admin_layout.html").read_text(encoding="utf-8")
    ui_tweaks = Path("web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8")

    # The dashboard still gets the report-status runtime through its shared
    # layout owner after the standalone /admin shell was retired.
    assert '{% extends "admin_layout.html" %}' in admin
    assert admin_layout.count(UI_TWEAKS) == 1
    assert 'if (pathname === "/admin")' in ui_tweaks
    assert "collectAdminReportTargets" in ui_tweaks
    assert "syncAdminOrderReportStates" in ui_tweaks
    assert "/dispatch/reports/statuses.json?order_ids=" in ui_tweaks
    assert "history-report-state-badge" in ui_tweaks
