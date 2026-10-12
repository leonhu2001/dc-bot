from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_SOURCE = (ROOT / "shared" / "db.py").read_text(encoding="utf-8")
REPAIR_SOURCE = (ROOT / "scripts" / "run_data_repairs.py").read_text(encoding="utf-8")


def test_database_initializer_does_not_run_historical_repairs() -> None:
    assert "apply_known_data_repairs" not in DB_SOURCE
    assert "purge_authorized_test_orders" not in DB_SOURCE


def test_historical_repairs_have_explicit_command() -> None:
    assert "apply_known_data_repairs" in REPAIR_SOURCE
    assert "purge_authorized_test_orders" in REPAIR_SOURCE
    assert "--include-authorized-test-cleanup" in REPAIR_SOURCE
