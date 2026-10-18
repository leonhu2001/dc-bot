from __future__ import annotations

from typing import Any

import discord

from services.web_sync.cs_review import (
    WEB_ORDER_PENDING_CS_DISPATCH,
    WebsiteOrderCsConfirmView,
    WebsitePendingCancelConfirmView,
    configure_web_sync_cs_review,
    _web_dashboard_db_path_for_bot,
    _web_cs_order_id_from_channel,
    _web_cs_set_status,
    _web_cs_ensure_review_panel,
)
from services.web_sync.order_created import (
    configure_web_sync_order_created,
    _process_web_order_created_event,
    _web_order_created_ensure_dispatch,
    _web_order_created_ensure_ticket,
    _web_order_created_find_dispatch_message,
    _web_order_created_seed_state,
)
from services.web_sync.self_service_bridge import (
    configure_web_sync_self_service_bridge,
    _r13_ensure_website_unified_panels,
    _r13_seed_website_order_into_self_service,
)


_CONFIGURED = False


def configure_web_sync_runtime_explicit(
    *,
    customer_category_id: int,
    customer_role_id: int,
    dispatch_channel_id: int,
    guild_id: int,
    order_claims: dict[int, dict[str, Any]],
    order_control_view_type: type[discord.ui.View],
    order_selections: dict[int, dict[str, Any]],
    bot_instance: discord.Client,
) -> None:
    """Compose Web Sync child runtimes using explicit dependencies only."""
    global _CONFIGURED

    configure_web_sync_self_service_bridge(
        customer_role_id=customer_role_id,
        order_control_view_type=order_control_view_type,
        order_selections=order_selections,
    )
    configure_web_sync_order_created(
        customer_category_id=customer_category_id,
        customer_role_id=customer_role_id,
        dispatch_channel_id=dispatch_channel_id,
        guild_id=guild_id,
        order_claims=order_claims,
        order_selections=order_selections,
        bot_instance=bot_instance,
    )
    configure_web_sync_cs_review(
        order_selections=order_selections,
        ensure_dispatch=lambda *args, **kwargs: _web_order_created_ensure_dispatch(
            *args, **kwargs
        ),
        seed_state=lambda *args, **kwargs: _web_order_created_seed_state(
            *args, **kwargs
        ),
    )
    _CONFIGURED = True
