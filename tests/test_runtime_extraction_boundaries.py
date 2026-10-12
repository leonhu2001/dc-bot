from pathlib import Path

from services.acceptance import runtime as acceptance_runtime
from services.web_sync import runtime as web_sync_runtime
from services import (
    order_credential_runtime,
    order_point_redemption,
    order_runtime,
    self_service_financials,
    self_service_runtime,
    ticket_identity,
)


def test_extracted_runtime_modules_import_without_importing_bot():
    assert callable(acceptance_runtime.configure_acceptance_runtime)
    assert callable(web_sync_runtime.configure_web_sync_runtime)
    assert callable(acceptance_runtime.process_acceptance_sync_events_once)
    assert callable(web_sync_runtime._process_web_order_created_event)
    assert callable(order_runtime.configure_order_runtime)
    assert callable(self_service_runtime.configure_self_service_runtime)
    assert callable(order_credential_runtime.configure_order_credentials)
    assert callable(order_point_redemption.configure_order_point_redemption)
    assert callable(self_service_financials.configure_self_service_financials)
    assert callable(ticket_identity.configure_ticket_identity)
    assert callable(order_runtime.finalize_accepted_pending_payment)
    assert callable(self_service_runtime.calculate_self_service_financials)


def test_runtime_dependency_binding_is_explicitly_deferred_to_bot_startup():
    bot_source = Path("bot.py").read_text(encoding="utf-8")

    acceptance_bind = bot_source.index("configure_acceptance_runtime(globals())")
    web_bind = bot_source.index("configure_web_sync_runtime(globals())")
    order_bind = bot_source.index("configure_order_runtime(globals())")
    self_service_bind = bot_source.index("configure_self_service_runtime(globals())")
    bot_run = bot_source.index("bot.run(TOKEN)")

    assert acceptance_bind < bot_run
    assert web_bind < bot_run
    assert order_bind < bot_run
    assert self_service_bind < bot_run


def test_large_runtime_implementations_no_longer_live_in_bot():
    bot_source = Path("bot.py").read_text(encoding="utf-8")

    assert "async def process_acceptance_sync_events_once" not in bot_source
    assert "async def refresh_acceptance_dispatch_from_web_order" not in bot_source
    assert "async def _web_order_created_ensure_ticket" not in bot_source
    assert "class WebsiteOrderCsConfirmView" not in bot_source
    assert "async def _process_web_order_created_event" not in bot_source
    assert "async def finalize_accepted_pending_payment" not in bot_source
    assert "class DispatchClaimView" not in bot_source
    assert "def calculate_self_service_financials" not in bot_source
    assert "class SelfServiceOrderView" not in bot_source
    assert "async def build_reorder_self_service_draft" not in bot_source

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


def test_phase2_order_runtime_responsibilities_are_physically_extracted():
    order_source = Path("services/order_runtime.py").read_text(encoding="utf-8")
    credentials_source = Path("services/order_credential_runtime.py").read_text(
        encoding="utf-8"
    )
    redemption_source = Path("services/order_point_redemption.py").read_text(
        encoding="utf-8"
    )
    persistence_source = Path("services/order_credentials.py").read_text(
        encoding="utf-8"
    )

    assert "async def finalize_accepted_pending_payment" in order_source
    assert "class DispatchClaimView" in order_source
    assert "class OrderCredentialModal" not in order_source
    assert "async def redeem_order_point_benefit_on_payment" not in order_source

    assert "class OrderCredentialModal" in credentials_source
    assert "async def ensure_order_credential_request" in credentials_source
    assert "async def redeem_order_point_benefit_on_payment" in redemption_source

    # Persistence and Discord UI/runtime are intentionally separate services.
    assert "def ensure_order_credential_tables" in persistence_source
    assert "def configure_order_credentials" not in persistence_source
    assert "from services.order_credentials import" in credentials_source


def test_phase2_self_service_financials_are_physically_extracted():
    self_service_source = Path("services/self_service_runtime.py").read_text(
        encoding="utf-8"
    )
    financials_source = Path("services/self_service_financials.py").read_text(
        encoding="utf-8"
    )

    assert "def calculate_self_service_financials" not in self_service_source
    assert "def calculate_manual_price_adjustment" not in self_service_source
    assert "class SelfServiceOrderView" in self_service_source
    assert "async def build_reorder_self_service_draft" in self_service_source

    assert "def calculate_self_service_financials" in financials_source
    assert "def calculate_manual_price_adjustment" in financials_source
    assert "def add_self_service_financial_breakdown_fields" in financials_source


def test_bot_ticket_identity_helpers_are_extracted():
    bot_source = Path("bot.py").read_text(encoding="utf-8")
    helper_source = Path("services/ticket_identity.py").read_text(encoding="utf-8")

    assert "def build_ticket_channel_name" not in bot_source
    assert "def get_order_customer_id_from_channel" not in bot_source
    assert "def build_ticket_channel_name" in helper_source
    assert "def get_order_customer_id_from_channel" in helper_source


def test_runtime_configure_binds_remaining_legacy_dependencies():
    acceptance_runtime.configure_acceptance_runtime(
        {"_acceptance_runtime_test_marker": object()}
    )
    web_sync_runtime.configure_web_sync_runtime(
        {"_web_sync_runtime_test_marker": object()}
    )
    order_runtime.configure_order_runtime(
        {"_order_runtime_test_marker": object()}
    )
    self_service_runtime.configure_self_service_runtime(
        {"_self_service_runtime_test_marker": object()}
    )

    assert hasattr(acceptance_runtime, "_acceptance_runtime_test_marker")
    assert hasattr(web_sync_runtime, "_web_sync_runtime_test_marker")
    assert hasattr(order_runtime, "_order_runtime_test_marker")
    assert hasattr(self_service_runtime, "_self_service_runtime_test_marker")
