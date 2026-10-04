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
    source = Path("bot.py").read_text(encoding="utf-8")

    assert "async def repair_pending_acceptance_dispatch_panels_once" in source
    assert "await repair_pending_acceptance_dispatch_panels_once(" in source

def test_generic_web_sync_atomically_claims_only_non_claim_events():
    source = Path("bot.py").read_text(encoding="utf-8")

    start = source.index("def _web_sync_fetch_pending_events")
    end = source.index("def _web_sync_get_assignments", start)
    body = source[start:end]

    assert 'conn.execute("BEGIN IMMEDIATE")' in body
    assert "e.event_type NOT IN ('order_claimed', 'order_unclaimed')" in body
    assert "SET status = 'processing'" in body
    assert "processed_at = datetime('now')" in body
    assert "cursor.rowcount != len(event_ids)" in body


def test_acceptance_worker_is_single_owner_for_claim_events():
    source = Path("bot.py").read_text(encoding="utf-8")

    start = source.index("async def process_acceptance_sync_events_once")
    end = source.index("async def acceptance_sync_event_worker", start)
    body = source[start:end]

    assert "from sqlalchemy import select, update" in body
    assert ".where(SyncEvent.status == SyncEventStatus.PENDING.value)" in body
    assert "claimed.rowcount != 1" in body
    assert '"admin_added_worker"' in body
    assert '"admin_removed_worker"' in body
    assert "await _refresh_existing_web_sync_dispatch(" in body
    assert "Legacy claim events already completed" in body

