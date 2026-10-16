import asyncio
import inspect
from types import SimpleNamespace

from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch
from services.self_service_dispatch_runtime import (
    _create_waiting_acceptance_order_once,
    create_waiting_acceptance_order,
)
from services.self_service_runtime import (
    SelfServiceSubmitNoteModal,
    create_waiting_acceptance_order_from_self_service,
)
from shared import web_order_sync


def test_self_service_dispatch_is_inert_until_canonical_order_is_ready():
    source = inspect.getsource(_create_waiting_acceptance_order_once)

    send = source.index("dispatch_message = await dispatch_channel.send(")
    provisional = source.index("view=None", send)
    upsert = source.index("upsert_web_order_from_dispatch(", send)
    acceptance_meta = source.index("create_or_update_acceptance_meta(", upsert)
    persist_claim = source.index("remember_claim_data(dispatch_message.id", acceptance_meta)
    unlock = source.index("await dispatch_message.edit(", persist_claim)
    alert = source.index("await send_initial_smart_dispatch_alert(", unlock)
    specified_dm = source.index("await send_specified_staff_dispatch_dms(", unlock)

    assert send < provisional < upsert < acceptance_meta < persist_claim < unlock
    assert unlock < alert
    assert unlock < specified_dm


def test_self_service_dispatch_persists_provisional_message_for_crash_cleanup():
    source = inspect.getsource(_create_waiting_acceptance_order_once)

    assert 'data["provisional_dispatch_message_id"] = dispatch_message.id' in source
    assert 'data["provisional_dispatch_channel_id"] = dispatch_channel.id' in source
    assert 'data.pop("provisional_dispatch_message_id", None)' in source
    assert 'data.pop("provisional_dispatch_channel_id", None)' in source


def test_runtime_owns_pre_activation_rollback_boundary():
    source = inspect.getsource(create_waiting_acceptance_order)

    assert "dispatch_rollback_pending" in source
    assert "cleanup_failed_self_service_dispatch(" in source
    assert "await _create_waiting_acceptance_order_once(" in source
    assert "provisional_dispatch_message_id" in source
    assert "raise" in source


def test_pre_activation_snapshots_and_dispatch_plan_are_fail_closed():
    source = inspect.getsource(_create_waiting_acceptance_order_once)
    unlock = source.index("await dispatch_message.edit(")

    web_snapshot_failure = source.index("WebOrder 規則／價格快照寫入失敗。")
    dispatch_plan_failure = source.index("智慧派單計畫建立失敗。")
    acceptance_snapshot_failure = source.index("接單規則／價格快照寫入失敗。")

    assert web_snapshot_failure < unlock
    assert dispatch_plan_failure < unlock
    assert acceptance_snapshot_failure < unlock
    assert "if result.rowcount != 1:" in source


def test_legacy_self_service_entrypoint_is_only_a_dependency_adapter():
    source = inspect.getsource(create_waiting_acceptance_order_from_self_service)

    assert "create_self_service_waiting_acceptance_order(" in source
    assert "SelfServiceDispatchDeps(" in source
    assert "upsert_web_order_from_dispatch(" not in source


def test_submit_note_failure_is_phase_aware_and_preserves_draft():
    source = inspect.getsource(SelfServiceSubmitNoteModal.on_submit)

    assert "provisional_started" in source
    assert "canonical_ready" in source
    assert "cleanup_failed_self_service_dispatch(" in source
    assert "原本填好的草稿仍保留" in source
    assert "為避免重複派單" in source


def test_failed_dispatch_cleanup_removes_canonical_side_effects_and_runtime_links():
    source = inspect.getsource(cleanup_failed_self_service_dispatch)

    assert "delete_web_order_by_ticket_channel(" in source
    assert "await message.delete()" in source
    assert "order_claims.pop(dispatch_message_id, None)" in source
    assert 'data.pop("payment_method", None)' in source
    assert 'data["closed"] = False' in source
    assert 'data["dispatch_rollback_pending"] = True' in source


def test_cleanup_before_provisional_dispatch_does_not_delete_web_order(monkeypatch):
    deleted = []
    remembered = []
    data = {"item": "甜蜜單", "quantity": 2, "payment_method": "待付款"}

    monkeypatch.setattr(
        web_order_sync,
        "delete_web_order_by_ticket_channel",
        lambda **kwargs: deleted.append(kwargs),
    )

    warnings = asyncio.run(
        cleanup_failed_self_service_dispatch(
            SimpleNamespace(guild=None),
            channel_id=6001,
            data=data,
            order_claims={},
            default_dispatch_channel_id=6002,
            remember_order=lambda *args: remembered.append(args),
            save_data=lambda: None,
            delete_claim_row=lambda **_kwargs: None,
        )
    )

    assert warnings == []
    assert deleted == []
    assert data["item"] == "甜蜜單"
    assert data["quantity"] == 2
    assert "payment_method" not in data
    assert remembered


def test_incomplete_cleanup_keeps_retry_pointer_but_not_live_order_links(monkeypatch):
    calls = []
    remembered = []
    data = {
        "item": "甜蜜單",
        "quantity": 2,
        "payment_method": "待付款",
        "provisional_dispatch_message_id": 7001,
        "provisional_dispatch_channel_id": 7002,
        "dispatch_message_id": 7001,
        "dispatch_channel_id": 7002,
        "web_order_id": 88,
        "status": "waiting_acceptance",
    }

    def fail_delete(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("db busy")

    monkeypatch.setattr(
        web_order_sync,
        "delete_web_order_by_ticket_channel",
        fail_delete,
    )

    warnings = asyncio.run(
        cleanup_failed_self_service_dispatch(
            SimpleNamespace(guild=None),
            channel_id=6001,
            data=data,
            order_claims={7001: {"status": "waiting_acceptance"}},
            default_dispatch_channel_id=7002,
            remember_order=lambda *args: remembered.append(args),
            save_data=lambda: None,
            delete_claim_row=lambda **_kwargs: None,
        )
    )

    assert warnings == ["網站訂單回滾失敗：RuntimeError"]
    assert data["dispatch_rollback_pending"] is True
    assert data["rollback_dispatch_message_id"] == 7001
    assert data["rollback_dispatch_channel_id"] == 7002
    assert data["rollback_web_order_id"] == 88
    assert "provisional_dispatch_message_id" not in data
    assert "dispatch_message_id" not in data
    assert "web_order_id" not in data
    assert "status" not in data
    assert data["item"] == "甜蜜單"
    assert data["quantity"] == 2
    assert remembered

    monkeypatch.setattr(
        web_order_sync,
        "delete_web_order_by_ticket_channel",
        lambda **kwargs: calls.append(kwargs),
    )

    retry_warnings = asyncio.run(
        cleanup_failed_self_service_dispatch(
            SimpleNamespace(guild=None),
            channel_id=6001,
            data=data,
            order_claims={},
            default_dispatch_channel_id=7002,
            remember_order=lambda *args: remembered.append(args),
            save_data=lambda: None,
            delete_claim_row=lambda **_kwargs: None,
        )
    )

    assert retry_warnings == []
    assert "dispatch_rollback_pending" not in data
    assert "rollback_dispatch_message_id" not in data
    assert calls[-1]["dispatch_message_id"] == 7001


def test_non_transactional_dispatch_logs_do_not_roll_back_ready_order():
    source = inspect.getsource(_create_waiting_acceptance_order_once)

    unlock = source.index("await dispatch_message.edit(")
    provisional_clear = source.index('data.pop("provisional_dispatch_message_id", None)', unlock)
    initial_alert = source.index("await send_initial_smart_dispatch_alert(", provisional_clear)
    order_log = source.index("await send_order_log(", initial_alert)
    proxy_log = source.index("await log_self_service_proxy_action(", order_log)
    success = source.index('return f"已送出等待接單：')

    assert unlock < provisional_clear < initial_alert < order_log < proxy_log < success
    assert "except Exception as exc:" in source[initial_alert:order_log]
    assert "[self-service-dispatch] order log failed" in source
    assert "[self-service-dispatch] proxy log failed" in source
