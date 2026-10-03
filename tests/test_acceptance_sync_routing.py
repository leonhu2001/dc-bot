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
