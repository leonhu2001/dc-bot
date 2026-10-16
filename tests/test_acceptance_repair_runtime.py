from pathlib import Path

from services.acceptance import repair_runtime, runtime


def test_acceptance_repair_functions_are_physically_extracted_and_reexported():
    runtime_source = Path("services/acceptance/runtime.py").read_text(encoding="utf-8")
    repair_source = Path("services/acceptance/repair_runtime.py").read_text(
        encoding="utf-8"
    )

    function_names = (
        "repair_pending_acceptance_dispatch_panels_once",
        "restore_acceptance_payment_panel_for_order",
        "repair_pending_acceptance_payment_panels_once",
        "repair_pending_acceptance_ticket_access_once",
    )

    for name in function_names:
        assert f"async def {name}" not in runtime_source
        assert f"async def {name}" in repair_source
        assert getattr(runtime, name) is getattr(repair_runtime, name)


def test_acceptance_repair_runtime_uses_canonical_web_order_storage():
    source = Path("services/acceptance/repair_runtime.py").read_text(encoding="utf-8")

    assert "from shared.db import SessionLocal" in source
    assert "from shared.models import WebOrder" in source
    assert "sqlite3" not in source
    assert "web_dashboard.db" not in source
    assert "Path(__file__)" not in source


def test_acceptance_repair_state_transition_stays_narrow():
    source = Path("services/acceptance/repair_runtime.py").read_text(encoding="utf-8")

    assert "target_status=ACCEPTED_PENDING_PAY" in source
    assert "WAITING_ACCEPTANCE" in source
    assert "expected_statuses={" in source
    assert "ACTIVE" not in source
    assert "CLOSED" not in source
