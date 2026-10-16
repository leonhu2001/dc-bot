from __future__ import annotations

import pytest

from core import database as core_database
from services import logging_service, orders
from services.acceptance import ticket_access
import services.order_dispatch_runtime as runtime


def _namespace() -> dict[str, object]:
    def apply_acceptance_state(*_args, **_kwargs):
        return None

    def member_display_name(member):
        return str(getattr(member, "id", "worker"))

    def member_role_ids(_member):
        return []

    def order_requires_credentials(_data):
        return False

    async def revoke_order_credential_messages(*_args, **_kwargs):
        return None

    async def send_acceptance_payment_panel_if_ready(*_args, **_kwargs):
        return None

    return {
        "BOOSTER_RECEIVER_ROLE_ID": 1,
        "DISPATCH_CHANNEL_ID": 2,
        "ORDER_CLAIMS": {},
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_apply_acceptance_state_to_claim_data": apply_acceptance_state,
        "_member_display_name": member_display_name,
        "_member_role_id_texts": member_role_ids,
        "_order_requires_credentials": order_requires_credentials,
        "revoke_order_credential_messages": revoke_order_credential_messages,
        "send_acceptance_payment_panel_if_ready": send_acceptance_payment_panel_if_ready,
    }


def _stable_dependencies() -> dict[str, object]:
    return {
        "delete_claim_row_from_db": core_database.delete_claim_row_from_db,
        "delete_order_row_from_db": core_database.delete_order_row_from_db,
        "remember_claim_data": core_database.remember_claim_data,
        "save_bot_data": core_database.save_bot_data,
        "grant_order_ticket_access": ticket_access.grant_order_ticket_access,
        "revoke_order_ticket_access": ticket_access.revoke_order_ticket_access,
        "send_order_log": logging_service.send_order_log,
        "_to_int": orders._to_int,
        "build_self_service_order_embed": orders.build_self_service_order_embed,
    }


def test_order_dispatch_runtime_dependency_names_are_explicit_and_reduced():
    assert runtime._DEPENDENCY_NAMES == (
        "BOOSTER_RECEIVER_ROLE_ID",
        "DISPATCH_CHANNEL_ID",
        "ORDER_CLAIMS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_apply_acceptance_state_to_claim_data",
        "_member_display_name",
        "_member_role_id_texts",
        "_order_requires_credentials",
        "revoke_order_credential_messages",
        "send_acceptance_payment_panel_if_ready",
    )


def test_order_dispatch_runtime_owns_stable_direct_dependencies():
    for name, dependency in _stable_dependencies().items():
        assert getattr(runtime, name) is dependency


def test_namespace_cannot_shadow_stable_order_dispatch_dependencies(monkeypatch):
    namespace = _namespace()
    namespace.update({name: object() for name in _stable_dependencies()})
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    runtime.configure_order_dispatch_runtime(namespace)

    assert runtime._CONFIGURED is True
    for name, dependency in _stable_dependencies().items():
        assert getattr(runtime, name) is dependency


def test_missing_order_dispatch_dependency_fails_before_binding(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(runtime, "BOOSTER_RECEIVER_ROLE_ID", sentinel, raising=False)
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    namespace = _namespace()
    namespace.pop("BOOSTER_RECEIVER_ROLE_ID")

    with pytest.raises(RuntimeError, match="BOOSTER_RECEIVER_ROLE_ID"):
        runtime.configure_order_dispatch_runtime(namespace)

    assert runtime.BOOSTER_RECEIVER_ROLE_ID is sentinel
    assert runtime._CONFIGURED is False


def test_complete_order_dispatch_namespace_binds_only_legacy_adapters(monkeypatch):
    namespace = _namespace()
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    runtime.configure_order_dispatch_runtime(namespace)

    assert runtime._CONFIGURED is True
    for name in runtime._DEPENDENCY_NAMES:
        assert getattr(runtime, name) is namespace[name]
