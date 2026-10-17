from pathlib import Path

# Phase 2 contract: moved responsibilities stay physically separated while the
# parent runtimes expose only the startup/configuration surface still in use.
from services.acceptance import dispatch_refresh as acceptance_dispatch_refresh
from services.acceptance import runtime as acceptance_runtime
from services.acceptance import sync_worker as acceptance_sync_worker
from services.web_sync import runtime as web_sync_runtime
from services import (
    order_credential_runtime,
    order_payment_runtime,
    order_point_redemption,
    order_runtime,
    order_storage_runtime,
    self_service_financials,
    self_service_reorder,
    self_service_runtime,
    self_service_ui_runtime,
    ticket_identity,
)


def test_extracted_runtime_modules_import_without_importing_bot():
    assert callable(acceptance_runtime.configure_acceptance_runtime_explicit)
    assert not hasattr(acceptance_runtime, "configure_acceptance_runtime")
    assert callable(web_sync_runtime.configure_web_sync_runtime)
    assert callable(acceptance_runtime.process_acceptance_sync_events_once)
    assert callable(acceptance_sync_worker.process_acceptance_sync_events_once)
    assert callable(web_sync_runtime._process_web_order_created_event)
    assert callable(order_runtime.configure_order_runtime)
    assert callable(order_storage_runtime.configure_order_storage_runtime)
    assert callable(self_service_runtime.configure_self_service_runtime_explicit)
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")
    assert callable(self_service_ui_runtime.configure_self_service_ui_runtime)
    assert callable(order_credential_runtime.configure_order_credentials)
    assert callable(order_point_redemption.configure_order_point_redemption)
    assert callable(order_payment_runtime.configure_order_payment_runtime)
    assert callable(self_service_financials.configure_self_service_financials)
    assert callable(self_service_reorder.configure_self_service_reorder)
    assert callable(ticket_identity.configure_ticket_identity)
    assert callable(order_runtime.finalize_accepted_pending_payment)
    assert callable(self_service_runtime.calculate_self_service_financials)


def test_runtime_dependency_binding_is_explicitly_deferred_to_bot_startup():
    bot_source = Path("bot.py").read_text(encoding="utf-8")

    acceptance_bind = bot_source.index("configure_acceptance_runtime_explicit(")
    web_bind = bot_source.index("configure_web_sync_runtime(globals())")
    order_bind = bot_source.index("configure_order_runtime(globals())")
    lifecycle_bind = bot_source.index("configure_order_lifecycle_runtime_explicit(")
    self_service_bind = bot_source.index("configure_self_service_runtime_explicit(")
    bot_run = bot_source.index("bot.run(TOKEN)")

    assert acceptance_bind < bot_run
    assert web_bind < bot_run
    assert order_bind < bot_run
    assert lifecycle_bind < bot_run
    assert self_service_bind < bot_run
    assert "configure_acceptance_runtime(globals())" not in bot_source
    assert "configure_order_lifecycle_runtime(globals())" not in bot_source
    assert "configure_self_service_runtime(globals())" not in bot_source


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
    acceptance_worker_source = Path(
        "services/acceptance/sync_worker.py"
    ).read_text(encoding="utf-8")
    web_source = Path("services/web_sync/runtime.py").read_text(
        encoding="utf-8"
    )

    acceptance_dispatch_source = Path(
        "services/acceptance/dispatch_refresh.py"
    ).read_text(encoding="utf-8")

    assert "async def process_acceptance_sync_events_once" not in acceptance_source
    assert "async def process_acceptance_sync_events_once" in acceptance_worker_source
    assert "async def refresh_acceptance_dispatch_from_web_order" not in acceptance_source
    assert "async def refresh_acceptance_dispatch_from_web_order" in acceptance_dispatch_source
    assert "async def send_acceptance_payment_panel_if_ready" not in acceptance_source
    assert "async def send_acceptance_payment_panel_if_ready" in acceptance_dispatch_source
    assert "import bot" not in acceptance_dispatch_source
    assert "from bot import" not in acceptance_dispatch_source
    assert (
        acceptance_runtime.refresh_acceptance_dispatch_from_web_order
        is acceptance_dispatch_refresh.refresh_acceptance_dispatch_from_web_order
    )
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

    payment_source = Path("services/order_payment_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "async def finalize_accepted_pending_payment" not in order_source
    assert callable(order_runtime.finalize_accepted_pending_payment)
    assert "async def finalize_accepted_pending_payment" in payment_source
    assert "def configure_order_payment_runtime" in payment_source
    assert "import bot" not in payment_source
    assert "from bot import" not in payment_source
    storage_source = Path("services/order_storage_runtime.py").read_text(
        encoding="utf-8"
    )
    dispatch_source = Path("services/order_dispatch_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "class DispatchClaimView" not in order_source
    assert callable(order_runtime.DispatchClaimView)
    assert "class DispatchClaimView" in dispatch_source
    assert "def configure_order_dispatch_runtime" in dispatch_source
    assert "import bot" not in dispatch_source
    assert "from bot import" not in dispatch_source
    assert "async def lock_dispatch_claim_panel" not in order_source
    assert "async def store_dispatch_claim_panel" not in order_source
    assert "async def resume_stored_order" not in order_source
    assert "async def lock_dispatch_claim_panel" in storage_source
    assert "async def store_dispatch_claim_panel" in storage_source
    assert "async def resume_stored_order" in storage_source
    assert "def configure_order_storage_runtime" in storage_source
    assert "import bot" not in storage_source
    assert "from bot import" not in storage_source
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
    reorder_source = Path("services/self_service_reorder.py").read_text(
        encoding="utf-8"
    )

    ui_source = Path("services/self_service_ui_runtime.py").read_text(encoding="utf-8")

    assert "class SelfServiceOrderView" not in self_service_source
    assert "class SelfServiceOrderView" in ui_source
    assert "class SelfServiceSubmitNoteModal" not in self_service_source
    assert "class SelfServiceSubmitNoteModal" in ui_source
    assert "class SelfServiceStaffPriceModal" not in self_service_source
    assert "class SelfServiceStaffPriceModal" in ui_source
    assert "import bot" not in ui_source
    assert "from bot import" not in ui_source
    assert self_service_runtime.SelfServiceOrderView is self_service_ui_runtime.SelfServiceOrderView
    assert self_service_runtime.build_self_service_panel_embed is self_service_ui_runtime.build_self_service_panel_embed
    assert "async def build_reorder_self_service_draft" not in self_service_source
    assert "async def create_reorder_ticket_from_closed_order" not in self_service_source
    assert "async def build_reorder_self_service_draft" in reorder_source
    assert "async def create_reorder_ticket_from_closed_order" in reorder_source
    assert "def configure_self_service_reorder" in reorder_source
    assert "import bot" not in reorder_source
    assert "from bot import" not in reorder_source

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


def _order_dispatch_namespace() -> dict[str, object]:
    async def async_noop(*_args, **_kwargs):
        return None

    return {
        "BOOSTER_RECEIVER_ROLE_ID": 1,
        "DISPATCH_CHANNEL_ID": 123,
        "ORDER_CLAIMS": {},
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_apply_acceptance_state_to_claim_data": lambda *_args, **_kwargs: None,
        "_member_display_name": lambda member: str(getattr(member, "id", "worker")),
        "_member_role_id_texts": lambda _member: [],
        "_order_requires_credentials": lambda _data: False,
        "revoke_order_credential_messages": async_noop,
        "send_acceptance_payment_panel_if_ready": async_noop,
    }


def test_runtime_configure_boundaries_match_current_migration_stage():
    acceptance_runtime.configure_acceptance_runtime_explicit(
        dispatch_channel_id=123,
        order_claims={},
        payment_method_view_type=object,
        order_selections={},
        bot_instance=object(),
        guild_id=456,
        refresh_existing_web_sync_dispatch=lambda *_args, **_kwargs: None,
    )
    if hasattr(web_sync_runtime, "_web_sync_runtime_test_marker"):
        delattr(web_sync_runtime, "_web_sync_runtime_test_marker")
    web_sync_runtime.configure_web_sync_runtime(
        {"_web_sync_runtime_test_marker": object()}
    )
    if hasattr(order_runtime, "_order_runtime_test_marker"):
        delattr(order_runtime, "_order_runtime_test_marker")
    order_runtime.configure_order_runtime(
        {
            **_order_dispatch_namespace(),
            "_order_runtime_test_marker": object(),
        }
    )
    self_service_runtime.configure_self_service_runtime_explicit(
        customer_category_id=111,
        customer_role_id=222,
        dispatch_channel_id=333,
        order_claims={},
        point_redeem_items=(),
        point_redeem_items_by_key={},
        order_selections={},
        order_control_view_type=object,
    )

    assert not hasattr(acceptance_runtime, "configure_acceptance_runtime")
    assert not hasattr(web_sync_runtime, "_web_sync_runtime_test_marker")
    assert not hasattr(order_runtime, "_order_runtime_test_marker")
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")
