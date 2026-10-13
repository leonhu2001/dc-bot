from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"target block not found in {path}")
    if text.count(old) != 1:
        raise RuntimeError(f"target block is not unique in {path}: {text.count(old)} matches")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


router = ROOT / "web/app/routers/admin_dashboard.py"
template = ROOT / "web/app/templates/admin.html"
css = ROOT / "web/app/static/css/mw_portal_r5.css"
tests = ROOT / "tests/test_admin_navigation.py"

replace_once(
    router,
    "from web.app.services.order_financial_edit import (\n    preserve_order_financial_gaps,\n)\n",
    "from web.app.services.order_financial_edit import (\n    preserve_order_financial_gaps,\n)\nfrom web.app.services.order_reporting import get_report_statuses\n",
)

replace_once(
    router,
    '''    status_classes = {\n        "pending_cs_dispatch":\n            "pending",\n\n        "waiting_acceptance":\n            "waiting",\n\n        "accepted_pending_pay":\n            "payment",\n\n        "active":\n            "active",\n\n        "paid":\n            "active",\n\n        "completed":\n            "done",\n\n        "closed":\n            "done",\n\n        "done":\n            "done",\n\n        "cancelled":\n            "cancelled",\n\n        "canceled":\n            "cancelled",\n    }\n''',
    '''    status_classes = {\n        "pending_cs_dispatch":\n            "pending",\n\n        "waiting_acceptance":\n            "waiting",\n\n        "accepted_pending_pay":\n            "payment",\n\n        "active":\n            "active",\n\n        "paid":\n            "active",\n\n        "completed":\n            "done",\n\n        "closed":\n            "done",\n\n        "done":\n            "done",\n\n        "cancelled":\n            "cancelled",\n\n        "canceled":\n            "cancelled",\n    }\n\n\n    report_status_labels = {\n        "missing":\n            "未報單",\n\n        "pending":\n            "待審核",\n\n        "changes_requested":\n            "需修改",\n\n        "approved":\n            "已報單",\n    }\n\n\n    report_status_classes = {\n        "missing":\n            "report-missing",\n\n        "pending":\n            "report-pending",\n\n        "changes_requested":\n            "report-changes-requested",\n\n        "approved":\n            "report-approved",\n    }\n''',
)

replace_once(
    router,
    '''    all_orders = list(\n        orders\n    )\n\n\n    # MAWAN 4A-2R6 dashboard meta\n''',
    '''    all_orders = list(\n        orders\n    )\n\n\n    # Report state is a separate lifecycle from the order state. Read it in one\n    # bulk lookup so the operations overview reflects the canonical reporting\n    # ledger instead of inferring \"已報單\" from a closed order.\n    report_status_by_order = get_report_statuses(\n        [\n            int(order.get("id") or 0)\n            for order in all_orders\n            if order.get("status") == "closed"\n        ]\n    )\n\n\n    for order in all_orders:\n        report_status = report_status_by_order.get(\n            int(order.get("id") or 0)\n        )\n\n        order["report_status"] = report_status\n        order["report_status_label"] = report_status_labels.get(\n            report_status,\n            "",\n        )\n        order["report_status_class"] = report_status_classes.get(\n            report_status,\n            "",\n        )\n\n\n    # MAWAN 4A-2R6 dashboard meta\n''',
)

replace_once(
    template,
    '''                        <span\n                            class="\n                                badge\n                                {{ order.status_class }}\n                            "\n                        >\n                            {{ order.status_label }}\n                        </span>\n\n                    </div>\n''',
    '''                        <span\n                            class="\n                                badge\n                                {{ order.status_class }}\n                            "\n                        >\n                            {{ order.status_label }}\n                        </span>\n\n                        {% if order.report_status %}\n\n                            <div class="order-report-badge-row">\n                                <span\n                                    class="\n                                        badge\n                                        {{ order.report_status_class }}\n                                    "\n                                >\n                                    {{ order.report_status_label }}\n                                </span>\n                            </div>\n\n                        {% endif %}\n\n                    </div>\n''',
)

replace_once(
    css,
    '''body.mw-r5-admin .mw-r5-legacy-body .badge.pending { color: #e7c98a; }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.waiting { color: var(--r5-blue); }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.payment { color: var(--r5-orange); }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.active { color: #a9dfbb; }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.cancelled { color: #efa6a6; }\n''',
    '''body.mw-r5-admin .mw-r5-legacy-body .badge.pending { color: #e7c98a; }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.waiting { color: var(--r5-blue); }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.payment { color: var(--r5-orange); }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.active { color: #a9dfbb; }\nbody.mw-r5-admin .mw-r5-legacy-body .badge.cancelled { color: #efa6a6; }\n\nbody.mw-r5-admin .mw-r5-legacy-body .order-report-badge-row {\n    margin-top: 5px;\n}\n\nbody.mw-r5-admin .mw-r5-legacy-body .badge.report-approved {\n    color: #a9dfbb;\n    border-color: rgba(123, 199, 154, .34);\n    background: rgba(123, 199, 154, .07);\n}\n\nbody.mw-r5-admin .mw-r5-legacy-body .badge.report-pending {\n    color: #e7c98a;\n    border-color: rgba(214, 176, 90, .34);\n    background: rgba(214, 176, 90, .07);\n}\n\nbody.mw-r5-admin .mw-r5-legacy-body .badge.report-missing {\n    color: #e8aa72;\n    border-color: rgba(214, 154, 98, .38);\n    background: rgba(214, 154, 98, .07);\n}\n\nbody.mw-r5-admin .mw-r5-legacy-body .badge.report-changes-requested {\n    color: #efa6a6;\n    border-color: rgba(223, 123, 123, .38);\n    background: rgba(223, 123, 123, .07);\n}\n''',
)

append = '''\n\ndef test_admin_dashboard_uses_canonical_report_status_badges():\n    dashboard = (TEMPLATES / "admin.html").read_text(encoding="utf-8")\n    router = (ROOT / "web" / "app" / "routers" / "admin_dashboard.py").read_text(\n        encoding="utf-8"\n    )\n    portal = (\n        ROOT / "web" / "app" / "static" / "css" / "mw_portal_r5.css"\n    ).read_text(encoding="utf-8")\n\n    assert "get_report_statuses" in router\n    assert 'order["report_status"] = report_status' in router\n    assert 'order["report_status_label"]' in router\n    assert "order.report_status_label" in dashboard\n    assert "order.report_status_class" in dashboard\n\n    for class_name in (\n        "report-approved",\n        "report-pending",\n        "report-missing",\n        "report-changes-requested",\n    ):\n        assert f".badge.{class_name}" in portal\n'''

test_text = tests.read_text(encoding="utf-8")
if "def test_admin_dashboard_uses_canonical_report_status_badges():" in test_text:
    raise RuntimeError("admin report badge test already exists")
tests.write_text(test_text.rstrip() + append + "\n", encoding="utf-8")

print("admin report badge patch applied")
