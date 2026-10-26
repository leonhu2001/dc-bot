from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web/app/static/css/pages/mobile_app_component_sizing_v7.css"
SHELLS = [
    ROOT / "web/app/templates/_customer_mobile_app_shell.html",
    ROOT / "web/app/templates/_employee_mobile_app_shell.html",
    ROOT / "web/app/templates/_admin_sidebar.html",
]


def test_mobile_v7_uses_one_control_and_card_scale() -> None:
    css = CSS.read_text(encoding="utf-8")
    for token in (
        "--v7-control-h: 44px",
        "--v7-control-sm: 40px",
        "--v7-icon-control: 40px",
        "--v7-shortcut-h: 70px",
        "--v7-stat-h: 72px",
        "--v7-card-pad: 12px",
    ):
        assert token in css


def test_mobile_v7_covers_primary_customer_components() -> None:
    css = CSS.read_text(encoding="utf-8")
    for selector in (
        ".mobile-v6-actions a",
        ".mobile-v6-quick-grid a",
        ".mobile-v6-category-strip a",
        ".order3-card",
        ".order3-open",
        ".experience-card",
        ".service-card",
        ".public-crew-card",
        ".public-crew-more",
        ".vip-level-card",
        ".mc-shortcuts > a",
        ".customer-order-card",
    ):
        assert selector in css


def test_mobile_v7_covers_employee_and_admin_components() -> None:
    css = CSS.read_text(encoding="utf-8")
    for selector in (
        ".employee-mobile-task-hub .mobile-task-action",
        ".ec-stat",
        ".salary-card",
        ".dispatch-order-card",
        ".dispatch-my-card",
        ".report-filter-bar",
        ".admin-mobile-task-hub .mobile-task-action",
        ".center-stat",
        ".history-ledger-stat",
        ".queue-row",
        ".workspace",
    ):
        assert selector in css


def test_mobile_v7_loads_after_v6_in_all_app_shells() -> None:
    for shell in SHELLS:
        text = shell.read_text(encoding="utf-8")
        v6 = text.index("mobile_app_rebuild_v6.css")
        v7 = text.index("mobile_app_component_sizing_v7.css")
        assert v7 > v6, shell.name
