from pathlib import Path

from sqlalchemy import create_engine, text

from web.app.services.order_reporting import ensure_order_reporting_tables


def _reporting_test_engine():
    test_engine = create_engine("sqlite:///:memory:")
    with test_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                closed_at DATETIME,
                updated_at DATETIME,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))
    return test_engine


def test_existing_closed_orders_are_backfilled_as_approved_legacy():
    test_engine = _reporting_test_engine()
    with test_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, status, closed_at, updated_at, created_at
            ) VALUES (
                1, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))

    ensure_order_reporting_tables(test_engine)

    with test_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT status, is_legacy
            FROM order_reports
            WHERE order_id = 1
        """)).mappings().one()

    assert row["status"] == "approved"
    assert int(row["is_legacy"]) == 1


def test_new_close_creates_missing_report_and_worker_reminder():
    test_engine = _reporting_test_engine()

    # Establish the deployment cutoff first. There are no closed legacy rows yet.
    ensure_order_reporting_tables(test_engine)

    with test_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, status, closed_at, updated_at, created_at
            ) VALUES (
                2, 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            INSERT INTO order_assignments (
                order_id, worker_discord_id, is_active
            ) VALUES (
                2, '123456789', 1
            )
        """))
        conn.execute(text("""
            UPDATE web_orders
            SET status = 'closed',
                closed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 2
        """))

    with test_engine.begin() as conn:
        report = conn.execute(text("""
            SELECT status, is_legacy
            FROM order_reports
            WHERE order_id = 2
        """)).mappings().one()
        reminder = conn.execute(text("""
            SELECT worker_discord_id, status, attempts
            FROM order_report_reminders
            WHERE order_id = 2
        """)).mappings().one()

    assert report["status"] == "missing"
    assert int(report["is_legacy"]) == 0
    assert reminder["worker_discord_id"] == "123456789"
    assert reminder["status"] == "pending"
    assert int(reminder["attempts"]) == 0

    # Re-running startup migrations must not turn a new missing report into legacy.
    ensure_order_reporting_tables(test_engine)
    with test_engine.begin() as conn:
        report_after_restart = conn.execute(text("""
            SELECT status, is_legacy
            FROM order_reports
            WHERE order_id = 2
        """)).mappings().one()

    assert report_after_restart["status"] == "missing"
    assert int(report_after_restart["is_legacy"]) == 0


def test_reporting_ui_contracts_are_present():
    root = Path(__file__).resolve().parents[1]
    router_source = (root / "web/app/routers/order_reports.py").read_text(encoding="utf-8")
    sidebar_source = (root / "web/app/templates/_employee_sidebar.html").read_text(encoding="utf-8")
    ui_source = (root / "web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8")

    assert '"/dispatch/reports"' in router_source
    assert '"/dispatch/reports/review"' in router_source
    assert "報單系統" in sidebar_source
    assert "target = \"_blank\"" in ui_source
    assert "/dispatch/reports/statuses.json" in ui_source

def test_reporting_status_badges_use_static_csp_safe_styles():
    root = Path(__file__).resolve().parents[1]
    css_source = (root / "web/app/static/css/pages/layout_inline_1.css").read_text(encoding="utf-8")
    ui_source = (root / "web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8")

    assert ".history-report-state-badge" in css_source
    assert 'data-status="missing"' in css_source
    assert 'data-status="pending"' in css_source
    assert 'data-status="changes_requested"' in css_source
    assert 'data-status="approved"' in css_source
    assert ".order-report-nav-count" in css_source
    assert "order-report-history-status-style" not in ui_source
    assert 'document.createElement("style")' not in ui_source
