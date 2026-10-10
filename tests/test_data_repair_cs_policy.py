from pathlib import Path


def test_mo20261007003_has_cs_only_correction_after_worker_point_repair():
    root = Path(__file__).resolve().parents[1]
    source = (root / "services/data_repairs.py").read_text(encoding="utf-8")
    assert "MO20261007003_CS_REPAIR_KEY" in source
    assert "repair_mo20261007003_customer_service_payout" in source
    assert "data_repair_exclude_gifted_service_from_cs_payout" in source
