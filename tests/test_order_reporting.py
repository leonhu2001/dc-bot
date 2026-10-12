from pathlib import Path


def test_order_reporting_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'web/app/routers/order_reports.py').exists()
    assert (root / 'web/app/services/order_reporting.py').exists()
    assert (root / 'web/app/templates/order_reports.html').exists()
