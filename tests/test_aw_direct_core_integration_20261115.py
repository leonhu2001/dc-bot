from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import order_runtime
from services import self_service_selection_state as selection
from services.aw_collision_catalog import (
    AW_RULE_KEYS,
    AwCollisionQuantityModal,
    validate_aw_quantity_for_rule,
)
from services.self_service_dispatch_runtime import create_waiting_acceptance_order
from services.self_service_ui_runtime import build_self_service_panel_embed


ROOT = Path(__file__).resolve().parents[1]
AW_KEY = AW_RULE_KEYS[1]


def test_aw_draft_confirmation_is_cleared_when_product_changes() -> None:
    data = {
        "order_rule_key": AW_KEY,
        "aw_collision_quantity_confirmed": True,
        "aw_collision_plan_key": AW_KEY,
        "aw_collision_unit_rate": "4.5",
        "aw_collision_quantity_set_by": 1234,
        "quantity": 250,
    }

    selection.clear_product_dependent_selection_state(data)

    assert data["quantity"] == 250
    assert all(
        key not in data
        for key in (
            "aw_collision_quantity_confirmed",
            "aw_collision_plan_key",
            "aw_collision_unit_rate",
            "aw_collision_quantity_set_by",
        )
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, "請先在第四欄"),
        ({"aw_collision_quantity_confirmed": True}, "與已填發數的方案不一致"),
        (
            {
                "aw_collision_quantity_confirmed": True,
                "aw_collision_plan_key": AW_KEY,
                "quantity": 501,
            },
            "第三欄更換方案",
        ),
        (
            {
                "aw_collision_quantity_confirmed": True,
                "aw_collision_plan_key": AW_KEY,
                "quantity": "不是數字",
            },
            "AW代撞發數異常",
        ),
    ],
)
def test_aw_dispatch_rejects_unconfirmed_mismatched_or_invalid_quantity_before_side_effects(
    payload, expected,
) -> None:
    data = {"order_rule_key": AW_KEY, **payload}
    deps = SimpleNamespace(order_selections={123: data})

    with pytest.raises(ValueError, match=expected):
        asyncio.run(
            create_waiting_acceptance_order(
                SimpleNamespace(),
                customer_id=456,
                channel_id=123,
                deps=deps,
            )
        )


def test_aw_quantity_modal_is_owned_by_core_select(monkeypatch) -> None:
    deps = SimpleNamespace(order_selections={
        999: {
            "order_rule_key": AW_KEY,
            "quantity": 250,
            "aw_collision_quantity_confirmed": True,
        },
        998: {"order_rule_key": "basic_tech_secret_single", "quantity": 1},
    })
    monkeypatch.setattr(order_runtime, "_require_runtime_state", lambda: deps)
    aw_select = order_runtime.SelfServiceOrderQuantitySelect(10, 999, "AW代撞", 250)
    assert aw_select._aw_collision_mode is True
    assert aw_select.custom_id == "self_service_order_quantity_select"
    assert aw_select.placeholder == "填寫發數"
    assert aw_select.options[0].value == "aw_collision_quantity_modal"
    assert aw_select.disabled is False

    ordinary = order_runtime.SelfServiceOrderQuantitySelect(10, 998, None, 1)
    assert ordinary._aw_collision_mode is False
    assert ordinary.disabled is True


def test_aw_core_panel_and_dispatch_are_not_runtime_rebound_by_installer() -> None:
    startup = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    aw_source = (ROOT / "services/aw_collision_catalog.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services/order_runtime.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "services/self_service_dispatch_runtime.py").read_text(encoding="utf-8")
    ui = (ROOT / "services/self_service_ui_runtime.py").read_text(encoding="utf-8")
    credentials = (ROOT / "services/order_credential_runtime.py").read_text(encoding="utf-8")

    assert "_install_aw_collision_catalog()" not in startup
    assert "dispatch.create_waiting_acceptance_order =" not in aw_source
    assert "order_runtime.SelfServiceOrderQuantitySelect =" not in aw_source
    assert "ui.build_self_service_panel_embed =" not in aw_source
    assert "selection._PRODUCT_DEPENDENT_KEYS =" not in aw_source
    assert "AwCollisionQuantityModal(" in runtime
    assert "aw_quantity_select_kwargs" in runtime
    assert "validate_aw_quantity_for_rule(rule_key, int(data.get" in dispatch
    assert "aw_collision_quantity_confirmed" in ui
    assert "請補充安全箱格數" in credentials
    assert inspect.iscoroutinefunction(create_waiting_acceptance_order)


def test_aw_tier_prices_stay_approved_after_direct_core_refactor() -> None:
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[0], 100)["rate_text"] == "5"
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[1], 101)["rate_text"] == "4.5"
    assert validate_aw_quantity_for_rule(AW_RULE_KEYS[2], 501)["rate_text"] == "4"
