from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "services" / "self_service_runtime.py"
SERVICE = ROOT / "services" / "self_service_selection_runtime.py"


def test_selection_ui_is_canonical_in_dedicated_service():
    parent = PARENT.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")

    assert "from services.self_service_selection_runtime import (" in parent
    assert "configure_self_service_selection_runtime(" in parent

    for symbol in (
        "def get_specified_staff_entries_for_rule(",
        "class SelfServiceSpecifiedStaffDropdown(",
        "class SelfServicePointBenefitSelect(",
        "class SelfServicePointBenefitView(",
        "class SelfServiceSpecifiedStaffDropdownView(",
        "ORDER_POINT_BENEFIT_SPECS = {",
    ):
        assert symbol not in parent
        assert symbol in service


def test_selection_runtime_import_smoke():
    module = importlib.import_module("services.self_service_selection_runtime")
    assert callable(module.configure_self_service_selection_runtime)
    assert issubclass(module.SelfServicePointBenefitView, module.discord.ui.View)
    assert issubclass(module.SelfServiceSpecifiedStaffDropdownView, module.discord.ui.View)


def test_selection_runtime_has_no_parent_or_bot_import_cycle():
    source = SERVICE.read_text(encoding="utf-8")
    assert "import bot" not in source
    assert "from bot import" not in source
    assert "import services.self_service_runtime" not in source
    assert "from services.self_service_runtime import" not in source


def test_parent_configures_selection_with_explicit_dependencies():
    source = PARENT.read_text(encoding="utf-8")
    for fragment in (
        "SELF_SERVICE_ORDER_SELECTIONS = order_selections",
        "POINT_REDEEM_ITEMS = point_redeem_items",
        "order_selections=SELF_SERVICE_ORDER_SELECTIONS",
        "point_redeem_items=POINT_REDEEM_ITEMS",
        "role_key_for_member=_role_key_for_member",
        "order_view_type=SelfServiceOrderView",
        "point_benefit_adapter=_adapt_order_point_benefit_for_rule",
    ):
        assert fragment in source

    assert 'SELF_SERVICE_ORDER_SELECTIONS = namespace["SELF_SERVICE_ORDER_SELECTIONS"]' not in source
    assert 'POINT_REDEEM_ITEMS = namespace["POINT_REDEEM_ITEMS"]' not in source
