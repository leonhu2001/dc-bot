import asyncio
import inspect
from types import SimpleNamespace

from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch
from services.self_service_runtime import (
    SelfServiceSubmitNoteModal,
    create_waiting_acceptance_order_from_self_service,
)
from shared import web_order_sync


def test_self_service_dispatch_is_inert_until_canonical_order_is_ready():
    source = inspect.getsource(create_waiting_acceptance_order_from_self_service)

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
    source = inspect.getsource(create_waiting_acceptance_order_from_self_service)

    assert 'data["provisional_dispatch_message_id"] = dispatch_message.id' in source
    assert 'data["provisional_dispatch_channel_id"] = dispatch_channel.id' in source
    assert 'data.pop("provisional_dispatch_message_id", None)' in source
    assert 'data.pop("provisional_dispatch_channel_id", None)' in source


def test_submit_note_failure_rolls_back_dispatch_without_dropping_draft():
    source = inspect.getsource(SelfServiceSubmitNoteModal.on_submit)

    assert "cleanup_failed_self_service_dispatch(" in source
    assert "原本填好的草稿仍保留" in source


def test_failed_dispatch_cleanup_removes_canonical_side_effects_and_runtime_links():
    source = inspect.getsource(cleanup_failed_self_service_dispatch)

    assert "delete_web_order_by_ticket_channel(" in source
    assert "await message.delete()" in source
    assert "order_claims.pop(dispatch_message_id, None)" in source
    assert 'data.pop("payment_method", None)' in source
    assert 'data["closed"] = False' in source


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


def test_non_transactional_dispatch_logs_do_not_roll_back_ready_order():
    source = inspect.getsource(create_waiting_acceptance_order_from_self_service)

    unlock = source.index("await dispatch_message.edit(")
    order_log = source.index("await send_order_log(", unlock)
    proxy_log = source.index("await log_self_service_proxy_action(", order_log)
    success = source.index('return f"已送出等待接單：')

    assert unlock < order_log < proxy_log < success
    assert "[self-service-dispatch] order log failed" in source
    assert "[self-service-dispatch] proxy log failed" in source
