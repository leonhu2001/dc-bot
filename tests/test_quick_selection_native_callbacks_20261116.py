from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services import order_runtime as runtime
from services import quick_order_v2_select_display as selects


ROOT = Path(__file__).resolve().parents[1]


def _state(data: dict, *, authorized: bool = True):
    return SimpleNamespace(
        order_selections={777: data},
        can_operate_self_service_order=lambda user, customer_id: authorized,
    )


def _component(value: str = "1"):
    return SimpleNamespace(
        channel_id=777,
        customer_id=222,
        values=[value],
    )


def _interaction():
    return SimpleNamespace(user=SimpleNamespace(id=222))


def test_quick_quantity_marked_only_for_allowed_real_selection(monkeypatch):
    data = {"quick_order_v2": True, "quantity": 1}
    monkeypatch.setattr(runtime, "_require_runtime_state", lambda: _state(data))

    selects.record_quick_order_select_action("quantity", _component("2"), _interaction())
    assert data["quick_order_quantity_selected"] is True

    data.pop("quick_order_quantity_selected")
    selects.record_quick_order_select_action("quantity", _component("need_item"), _interaction())
    assert "quick_order_quantity_selected" not in data

    monkeypatch.setattr(runtime, "_require_runtime_state", lambda: _state(data, authorized=False))
    selects.record_quick_order_select_action("quantity", _component("2"), _interaction())
    assert "quick_order_quantity_selected" not in data


@pytest.mark.parametrize("action", ["category", "item", "detail"])
def test_new_quick_selection_clears_previous_quantity_marker(monkeypatch, action):
    data = {"quick_order_v2": True, "quick_order_quantity_selected": True}
    monkeypatch.setattr(runtime, "_require_runtime_state", lambda: _state(data))

    selects.record_quick_order_select_action(action, _component("change"), _interaction())
    assert "quick_order_quantity_selected" not in data


def test_invalid_detail_is_fail_closed_but_category_item_keep_old_behavior(monkeypatch):
    data = {"quick_order_v2": True, "quick_order_quantity_selected": True}
    monkeypatch.setattr(runtime, "_require_runtime_state", lambda: _state(data, authorized=False))

    selects.record_quick_order_select_action("detail", _component("change"), _interaction())
    assert data["quick_order_quantity_selected"] is True
    selects.record_quick_order_select_action("detail", _component("need_item"), _interaction())
    assert data["quick_order_quantity_selected"] is True

    # Mirrors the old wrappers: category/item marker-clearing is fail-open.
    selects.record_quick_order_select_action("item", _component("change"), _interaction())
    assert "quick_order_quantity_selected" not in data


def test_non_quick_ticket_is_not_modified(monkeypatch):
    data = {"category": "farm", "quick_order_quantity_selected": True}
    monkeypatch.setattr(runtime, "_require_runtime_state", lambda: _state(data))
    for action in ("category", "item", "detail", "quantity"):
        selects.record_quick_order_select_action(action, _component("2"), _interaction())
    assert data["quick_order_quantity_selected"] is True


def test_marker_bookkeeping_failure_never_blocks_actual_selection(monkeypatch):
    def broken_runtime():
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(runtime, "_require_runtime_state", broken_runtime)
    assert selects.record_quick_order_select_action(
        "quantity", _component("2"), _interaction()
    ) is None


def test_four_callbacks_remain_in_canonical_module_and_no_runtime_reassignment():
    source = (ROOT / "services/order_runtime.py").read_text(encoding="utf-8")
    helper = (ROOT / "services/quick_order_v2_select_display.py").read_text(encoding="utf-8")

    for cls in (
        runtime.SelfServiceOrderCategorySelect,
        runtime.SelfServiceOrderItemSelect,
        runtime.SelfServiceOrderDetailSelect,
        runtime.SelfServiceOrderQuantitySelect,
    ):
        assert cls.callback.__module__ == "services.order_runtime"

    for action in ("category", "item", "detail", "quantity"):
        assert f'record_quick_order_select_action("{action}", self, interaction)' in source

    assert "def _install_selection_markers" not in helper
    assert "_ORIGINAL_QUANTITY_CALLBACK" not in helper
    assert "_ORIGINAL_DETAIL_CALLBACK" not in helper
    assert "_ORIGINAL_ITEM_CALLBACK" not in helper
    assert "_ORIGINAL_CATEGORY_CALLBACK" not in helper
    assert "runtime.SelfServiceOrderQuantitySelect.callback =" not in helper
    assert "runtime.SelfServiceOrderDetailSelect.callback =" not in helper
    assert "runtime.SelfServiceOrderItemSelect.callback =" not in helper
    assert "runtime.SelfServiceOrderCategorySelect.callback =" not in helper


def test_select_display_still_reuses_legacy_four_selector_flag():
    assert selects.LEGACY_RESELECT_FLAG == "legacy_four_selector_panel"
    source = (ROOT / "services/quick_order_v2_select_display.py").read_text(encoding="utf-8")
    assert "def apply_quick_order_select_display" in source
    assert "_apply_classic_reselect_display(" in source
