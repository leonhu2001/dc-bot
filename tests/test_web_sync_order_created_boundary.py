import inspect
from pathlib import Path

from services.web_sync import order_created
from services.web_sync import runtime as web_sync_runtime


EXPECTED_ORDER_CREATED_DEPENDENCIES = {
    "customer_category_id",
    "customer_role_id",
    "dispatch_channel_id",
    "guild_id",
    "order_claims",
    "order_selections",
    "bot_instance",
}


def test_web_sync_order_created_uses_explicit_dependencies():
    signature = inspect.signature(order_created.configure_web_sync_order_created)
    assert set(signature.parameters) == EXPECTED_ORDER_CREATED_DEPENDENCIES
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_order_created_pipeline_is_physically_extracted():
    runtime_source = Path("services/web_sync/runtime.py").read_text(
        encoding="utf-8"
    )
    owner_source = Path("services/web_sync/order_created.py").read_text(
        encoding="utf-8"
    )

    definitions = (
        "async def _web_order_created_ensure_ticket",
        "async def _web_order_created_find_dispatch_message",
        "async def _web_order_created_ensure_dispatch",
        "def _web_order_created_seed_state",
        "async def _process_web_order_created_event",
    )
    for definition in definitions:
        assert definition not in runtime_source
        assert definition in owner_source

    assert "globals()" not in owner_source
    assert "import bot" not in owner_source
    assert "from bot import" not in owner_source
    assert (
        web_sync_runtime._process_web_order_created_event
        is order_created._process_web_order_created_event
    )
    assert (
        web_sync_runtime._web_order_created_ensure_dispatch
        is order_created._web_order_created_ensure_dispatch
    )
    assert (
        web_sync_runtime._web_order_created_seed_state
        is order_created._web_order_created_seed_state
    )


def test_web_sync_order_created_binds_shared_selection_state():
    claims = {}
    selections = {}
    bot_instance = object()
    order_created.configure_web_sync_order_created(
        customer_category_id=1,
        customer_role_id=2,
        dispatch_channel_id=3,
        guild_id=4,
        order_claims=claims,
        order_selections=selections,
        bot_instance=bot_instance,
    )
    assert order_created.ORDER_CLAIMS is claims
    assert order_created.SELF_SERVICE_ORDER_SELECTIONS is selections
    assert order_created.bot is bot_instance
