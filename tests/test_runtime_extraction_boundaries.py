from pathlib import Path

from services.acceptance import runtime as acceptance_runtime
from services.web_sync import runtime as web_sync_runtime


def test_extracted_runtime_modules_import_without_importing_bot():
    assert callable(acceptance_runtime.configure_acceptance_runtime)
    assert callable(web_sync_runtime.configure_web_sync_runtime)
    assert callable(acceptance_runtime.process_acceptance_sync_events_once)
    assert callable(web_sync_runtime._process_web_order_created_event)


def test_runtime_dependency_binding_is_explicitly_deferred_to_bot_startup():
    bot_source = Path("bot.py").read_text(encoding="utf-8")

    acceptance_bind = bot_source.index("configure_acceptance_runtime(globals())")
    web_bind = bot_source.index("configure_web_sync_runtime(globals())")
    bot_run = bot_source.index("bot.run(TOKEN)")

    assert acceptance_bind < bot_run
    assert web_bind < bot_run


def test_large_runtime_implementations_no_longer_live_in_bot():
    bot_source = Path("bot.py").read_text(encoding="utf-8")

    assert "async def process_acceptance_sync_events_once" not in bot_source
    assert "async def refresh_acceptance_dispatch_from_web_order" not in bot_source
    assert "async def _web_order_created_ensure_ticket" not in bot_source
    assert "class WebsiteOrderCsConfirmView" not in bot_source
    assert "async def _process_web_order_created_event" not in bot_source

    acceptance_source = Path("services/acceptance/runtime.py").read_text(
        encoding="utf-8"
    )
    web_source = Path("services/web_sync/runtime.py").read_text(
        encoding="utf-8"
    )

    assert "async def process_acceptance_sync_events_once" in acceptance_source
    assert "async def refresh_acceptance_dispatch_from_web_order" in acceptance_source
    assert "async def _web_order_created_ensure_ticket" in web_source
    assert "class WebsiteOrderCsConfirmView" in web_source
    assert "async def _process_web_order_created_event" in web_source


def test_runtime_configure_binds_remaining_legacy_dependencies():
    acceptance_runtime.configure_acceptance_runtime(
        {"_acceptance_runtime_test_marker": object()}
    )
    web_sync_runtime.configure_web_sync_runtime(
        {"_web_sync_runtime_test_marker": object()}
    )

    assert hasattr(acceptance_runtime, "_acceptance_runtime_test_marker")
    assert hasattr(web_sync_runtime, "_web_sync_runtime_test_marker")
