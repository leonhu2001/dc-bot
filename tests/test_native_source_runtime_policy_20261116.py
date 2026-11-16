"""No new business rules may be installed by rebinding functions at runtime."""
from __future__ import annotations

from pathlib import Path

from services import quick_order_v2, self_service_financials
from services import self_service_ui_runtime as ui
from services import self_service_companion_count_runtime as companion
from services import self_service_financial_copy as finance_copy
from services import order_ticket_name_restore_runtime as ticket_names
from services import quick_order_v2_production as production


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_final_companion_view_owned_by_main_ui_module_not_startup_patch():
    assert ui.SelfServiceOrderView.__module__ == "services.self_service_ui_runtime"
    assert companion.EnhancedSelfServiceOrderView is ui.SelfServiceOrderView
    assert companion.install_self_service_companion_count_runtime() is ui.SelfServiceOrderView
    assert "base_ui.SelfServiceOrderView =" not in _source(
        "services/self_service_companion_count_runtime.py"
    )


def test_finance_snapshot_and_copy_are_source_owned():
    assert self_service_financials.calculate_self_service_financials.__module__ == (
        "services.self_service_financials"
    )
    before = self_service_financials.calculate_self_service_financials
    finance_copy.install_self_service_financial_copy_policy()
    assert self_service_financials.calculate_self_service_financials is before
    code = _source("services/self_service_financial_copy.py")
    assert "financials.calculate_self_service_financials =" not in code
    assert "financials.add_self_service_financial_breakdown_fields =" not in code
    assert "setattr(runtime, name, value)" not in code
    assert "_SETTLED_FINANCIAL_KEYS" in code


def test_ticket_name_is_native_at_creation_store_and_successful_payment():
    policy = _source("services/order_ticket_name_restore_runtime.py")
    assert "quick._create_ticket =" not in policy
    assert "order_runtime._RUNTIME_STATE =" not in policy
    assert "order_payment_runtime.rename_ticket_channel =" not in policy
    assert "names._order_prefix =" not in _source(
        "services/order_ticket_ui_policy.py"
    )
    for path in (
        "services/quick_order_v2.py",
        "services/order_runtime.py",
        "services/order_payment_runtime.py",
    ):
        assert "order_ticket_name_restore_runtime" in _source(path)
    paid = _source("services/order_payment_runtime.py")
    assert paid.index('data["status"] = "active"') < paid.index(
        "payment_prefix = resolve_order_ticket_prefix("
    )


def test_public_panel_and_checkout_ui_use_direct_core_calls():
    quick_source = _source("services/quick_order_v2.py")
    prod_source = _source("services/quick_order_v2_production.py")
    ui_source = _source("services/self_service_ui_runtime.py")
    assert "return _public_view_for_channel(int(channel_id))" in quick_source
    assert "await _clean_ensure_panel(bot, int(channel_id))" in quick_source
    assert "quick._view_for_channel =" not in prod_source
    assert "quick._ensure_panel =" not in prod_source
    assert "ui.SelfServiceOrderView.__init__ =" not in prod_source
    assert "ui.build_self_service_panel_embed =" not in prod_source
    assert "apply_production_ticket_view_policy(" in ui_source
    assert "decorate_production_ticket_embed(" in ui_source
    assert callable(production.apply_production_ticket_view_policy)
    assert callable(production.decorate_production_ticket_embed)
