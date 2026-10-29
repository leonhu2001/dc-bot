import asyncio

from services import order_storage_composition as composition


def test_order_storage_composition_binds_service_owned_dependencies(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        composition,
        "configure_order_storage_runtime",
        lambda **kwargs: captured.update(kwargs),
    )

    claims = {}
    selections = {}
    composition.configure_order_storage_composition(123, claims, selections)

    from services.self_service_runtime import _get_rule_from_self_service_data

    assert captured["dispatch_channel_id"] == 123
    assert captured["order_claims"] is claims
    assert captured["self_service_order_selections"] is selections
    assert captured["dispatch_claim_view"] is composition.DispatchClaimView
    assert captured["order_category_labels"] is composition.ORDER_CATEGORY_LABELS
    assert captured["to_int"] is composition._to_int
    assert captured["self_service_order_embed_builder"] is composition.build_self_service_order_embed
    assert captured["acceptance_state_applier"] is composition._apply_acceptance_state_to_claim_data
    assert captured["self_service_rule_getter"] is _get_rule_from_self_service_data
    assert captured["claim_row_deleter"] is composition.delete_claim_row_from_db
    assert captured["initial_dispatch_preparer"] is composition.prepare_initial_smart_dispatch
    assert captured["initial_dispatch_alert_sender"] is composition.send_initial_smart_dispatch_alert
    assert captured["specified_staff_dm_sender"] is composition.send_specified_staff_dispatch_dms
    assert captured["specified_dm_result_setter"] is composition.set_specified_dm_results
    assert captured["web_order_status_syncer"] is composition._schedule_web_order_status_sync


def test_web_order_status_sync_scheduler_is_non_blocking_and_preserves_ticket_order(monkeypatch):
    calls = []

    async def fake_to_thread(func, **kwargs):
        calls.append((kwargs["ticket_channel_id"], kwargs["status"]))
        await asyncio.sleep(0)

    monkeypatch.setattr(composition.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(composition, "sync_web_order_status_from_bot", lambda **kwargs: None)
    composition._WEB_SYNC_TASKS.clear()
    composition._WEB_SYNC_TAILS.clear()

    async def run_scenario():
        composition._schedule_web_order_status_sync(
            ticket_channel_id=123,
            status="stored",
        )
        composition._schedule_web_order_status_sync(
            ticket_channel_id=123,
            status="pending",
        )

        # Scheduling itself must not wait for the blocking DB sync.
        assert calls == []

        tasks = list(composition._WEB_SYNC_TASKS)
        await asyncio.gather(*tasks)

    asyncio.run(run_scenario())

    assert calls == [(123, "stored"), (123, "pending")]
    assert composition._WEB_SYNC_TASKS == set()
    assert composition._WEB_SYNC_TAILS == {}
