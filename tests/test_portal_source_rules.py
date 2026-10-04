from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_layout_has_no_post_load_targeted_runtime_patch():
    layout = _read("web/app/templates/layout.html")

    assert "MAWAN_R5R6_TARGETED_FIX_V2_PORTAL_RUNTIME" not in layout
    assert "markPayoutMetrics" not in layout
    assert "markOrderStatus" not in layout
    assert "centerButtons" not in layout


def test_payout_metric_classes_are_attached_in_template():
    template = _read("web/app/templates/admin_payout_summary.html")

    assert template.count("mw-r56-payout-metric") == 4
    assert template.count("mw-r56-payout-value") == 4


def test_order_status_classes_are_attached_in_template():
    template = _read("web/app/templates/order_history.html")

    assert "history-status-cell mw-r56-order-status-cell" in template
    assert "history-status-select mw-r56-order-status-select" in template
