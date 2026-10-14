from core import database as core_database
from core import time_utils
from services.acceptance import runtime as acceptance_runtime


def test_acceptance_runtime_owns_canonical_persistence_and_time_dependencies():
    assert acceptance_runtime.remember_claim_data is core_database.remember_claim_data
    assert acceptance_runtime.remember_order_data is core_database.remember_order_data
    assert acceptance_runtime.save_bot_data is core_database.save_bot_data
    assert acceptance_runtime.get_taipei_now_iso is time_utils.get_taipei_now_iso


def test_acceptance_legacy_injection_cannot_shadow_module_owned_dependencies():
    originals = {
        "remember_claim_data": acceptance_runtime.remember_claim_data,
        "remember_order_data": acceptance_runtime.remember_order_data,
        "save_bot_data": acceptance_runtime.save_bot_data,
        "get_taipei_now_iso": acceptance_runtime.get_taipei_now_iso,
    }
    marker = object()

    acceptance_runtime.configure_acceptance_runtime(
        {
            **{name: object() for name in originals},
            "_acceptance_runtime_boundary_marker": marker,
        }
    )

    for name, original in originals.items():
        assert getattr(acceptance_runtime, name) is original
    assert acceptance_runtime._acceptance_runtime_boundary_marker is marker


def test_acceptance_owned_dependency_names_are_explicit():
    assert acceptance_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "get_taipei_now_iso",
            "remember_claim_data",
            "remember_order_data",
            "save_bot_data",
        }
    )
