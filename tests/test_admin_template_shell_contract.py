from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
CSS = ROOT / "web" / "app" / "static" / "css" / "pages"

# Reviewed 2026-10-26. These older pages still own their outer document, but all
# direct sidebar rendering goes through the same _admin_sidebar component. New
# standalone admin shells must not be added silently.
LEGACY_STANDALONE_ADMIN_TEMPLATES = {
    "admin_customer_detail.html",
    "admin_customers.html",
    "admin_fun_orders.html",
    "admin_lottery.html",
    "admin_order_detail.html",
    "admin_roulette.html",
    "admin_staff.html",
    "admin_staff_detail.html",
    "admin_staff_profile_edit_r5.html",
    "admin_staff_profiles_r5.html",
    "admin_vip_timer_detail.html",
    "admin_vip_timers.html",
}

_EXTENDS_RE = re.compile(r'{%\s*extends\s+["\']([^"\']+)["\']\s*%}')


def _direct_standalone_admin_templates() -> set[str]:
    offenders: set[str] = set()
    for path in sorted(TEMPLATES.glob("admin_*.html")):
        if path.name == "admin_layout.html":
            continue
        source = path.read_text(encoding="utf-8")
        if "<!doctype html" in source.lower() or '{% include "_admin_sidebar.html" %}' in source:
            offenders.add(path.name)
            continue
        match = _EXTENDS_RE.search(source)
        if match and match.group(1).startswith("admin_"):
            continue
        if '{% extends "admin_layout.html" %}' not in source and '{% extends "layout.html" %}' not in source:
            offenders.add(path.name)
    return offenders


def test_legacy_standalone_admin_shell_inventory_is_explicit() -> None:
    assert _direct_standalone_admin_templates() == LEGACY_STANDALONE_ADMIN_TEMPLATES


def test_no_unreviewed_template_directly_owns_admin_sidebar() -> None:
    owners: set[str] = set()
    for path in sorted(TEMPLATES.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        if '{% include "_admin_sidebar.html" %}' in source:
            owners.add(path.name)

    assert owners == LEGACY_STANDALONE_ADMIN_TEMPLATES | {"admin_layout.html"}


def test_all_reviewed_legacy_shells_share_admin_sidebar_scope() -> None:
    for name in sorted(LEGACY_STANDALONE_ADMIN_TEMPLATES):
        source = (TEMPLATES / name).read_text(encoding="utf-8")
        assert '{% include "_admin_sidebar.html" %}' in source, name
        assert "mw-r5-admin" in source, name
        assert "mw_portal_r5.css" in source, name


def test_admin_sidebar_visual_rules_have_one_component_owner() -> None:
    sidebar = (TEMPLATES / "_admin_sidebar.html").read_text(encoding="utf-8")
    component = (CSS / "admin_sidebar.css").read_text(encoding="utf-8")
    shell = (CSS / "admin_shell_layout.css").read_text(encoding="utf-8")

    assert "admin_sidebar.css?v=20261026-1" in sidebar
    assert ".mw-r5-nav-section" in component
    assert ".mw-r5-nav-section" not in shell
