from pathlib import Path

from web.app.services.order_service import is_prepay_acceptance_sync_event


def test_prepay_acceptance_sync_event_detection():
    assert is_prepay_acceptance_sync_event(
        "order_claimed",
        {"prepay_acceptance": True},
    )
    assert is_prepay_acceptance_sync_event(
        "order_unclaimed",
        {"prepay_acceptance": True},
    )

    assert not is_prepay_acceptance_sync_event(
        "order_claimed",
        {"prepay_acceptance": False},
    )
    assert not is_prepay_acceptance_sync_event(
        "order_updated",
        {"prepay_acceptance": True},
    )


def test_bot_generic_web_sync_does_not_consume_prepay_acceptance_events():
    source = Path("bot.py").read_text(encoding="utf-8")

    process_start = source.index("async def process_one_web_sync_event")
    process_end = source.index(
        "async def _process_existing_web_sync_event",
        process_start,
    )
    process_body = source[process_start:process_end]

    assert "is_prepay_acceptance_sync_event" in process_body
    assert "return" in process_body


def test_bot_startup_reconciles_existing_acceptance_panels():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    runtime_source = Path("services/acceptance/runtime.py").read_text(
        encoding="utf-8"
    )
    repair_source = Path("services/acceptance/repair_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "async def repair_pending_acceptance_dispatch_panels_once" not in runtime_source
    assert "repair_pending_acceptance_dispatch_panels_once," in runtime_source
    assert "async def repair_pending_acceptance_dispatch_panels_once" in repair_source
    assert "await repair_pending_acceptance_dispatch_panels_once(" in bot_source


def test_generic_web_sync_atomically_claims_only_non_claim_events():
    source = Path("services/web_sync/event_store.py").read_text(
        encoding="utf-8"
    )

    start = source.index("def claim_pending_events")
    end = source.index("def get_assignments", start)
    body = source[start:end]

    assert 'conn.execute("BEGIN IMMEDIATE")' in body
    assert "e.event_type NOT IN ('order_claimed', 'order_unclaimed')" in body
    assert "SET status = 'processing'" in body
    assert "processed_at = datetime('now')" in body
    assert "cursor.rowcount != len(event_ids)" in body


def test_acceptance_worker_retries_failed_and_abandoned_claim_events():
    source = Path("services/acceptance/sync_worker.py").read_text(
        encoding="utf-8"
    )

    start = source.index("async def process_acceptance_sync_events_once")
    end = source.index("async def acceptance_sync_event_worker", start)
    body = source[start:end]

    assert "ACCEPTANCE_SYNC_STALE_PROCESSING_MINUTES = 10" in source
    assert "ACCEPTANCE_SYNC_MAX_RETRIES = 20" in source
    assert "SyncEvent.status == SyncEventStatus.PENDING.value" in body
    assert "SyncEvent.status == SyncEventStatus.FAILED.value" in body
    assert "SyncEvent.status == SyncEventStatus.PROCESSING.value" in body
    assert "SyncEvent.processed_at <= stale_before" in body
    assert "retry_count_expr < ACCEPTANCE_SYNC_MAX_RETRIES" in body
    assert "claimed.rowcount != 1" in body
    assert "error_message=None" in body
    assert '"admin_added_worker"' in body
    assert '"admin_removed_worker"' in body
    assert "await deps.refresh_existing_web_sync_dispatch(" in body
    assert "if not is_prepay_acceptance and not is_admin_worker_change:" in body
    assert "event.status = SyncEventStatus.DONE.value" in body


def test_cs_dispatch_failure_does_not_claim_rollback_succeeded_when_it_failed():
    source = Path("services/web_sync/cs_review.py").read_text(
        encoding="utf-8"
    )

    marker = source.index("CS dispatch rollback failed")
    start = source.rfind("except Exception as exc:", 0, marker)
    end = source.index("# MAWAN_R12_WEBSITE_PENDING_CANCEL", marker)
    body = source[start:end]

    assert "rollback_error = None" in body
    assert "except Exception as rollback_exc:" in body
    assert "CS dispatch rollback failed" in body
    assert "if rollback_error is None:" in body
    assert "訂單狀態沒有成功恢復" in body
