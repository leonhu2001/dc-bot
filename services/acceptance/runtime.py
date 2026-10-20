from __future__ import annotations

from core.database import remember_claim_data, remember_order_data, save_bot_data

import discord

from services.acceptance.dispatch_refresh import (
    _apply_acceptance_state_to_claim_data as _apply_acceptance_state_to_claim_data_base,
    _build_receiver_text_from_claim_data,
    configure_acceptance_dispatch_refresh,
    refresh_acceptance_dispatch_from_web_order,
    send_acceptance_payment_panel_if_ready,
)
from services.acceptance.payment_panel import (
    acceptance_staff_display_text,
    ensure_acceptance_payment_panel,
    invalidate_acceptance_payment_panel,
)
from services.acceptance.repair_runtime import (
    configure_acceptance_repair_runtime,
    repair_pending_acceptance_dispatch_panels_once,
    repair_pending_acceptance_payment_panels_once,
    repair_pending_acceptance_ticket_access_once,
    restore_acceptance_payment_panel_for_order,
)
from services.acceptance.sync_worker import (
    acceptance_sync_event_worker,
    configure_acceptance_sync_worker,
    process_acceptance_sync_events_once,
)
from services.acceptance.ticket_access import (
    _ticket_overwrite_has_values,
    grant_order_ticket_access,
    revoke_order_ticket_access,
    sync_acceptance_ticket_access_from_state,
)
from services.order_dispatch_runtime import DispatchClaimView
from services.orders import (
    ORDER_CATEGORY_LABELS,
    _to_int,
    build_self_service_order_embed,
)
from services.self_service_financials import (
    _format_plain_amount,
    _price_int,
    _price_snapshot,
    add_self_service_financial_breakdown_fields,
)
from services.vip_timer_acceptance import configure_vip_timer_acceptance


def configure_acceptance_runtime_explicit(
    *,
    dispatch_channel_id: int,
    order_claims: dict,
    payment_method_view_type,
    order_selections: dict,
    bot_instance,
    guild_id: int,
    refresh_existing_web_sync_dispatch,
) -> None:
    """Bind the acceptance runtime from explicit bot-owned dependencies."""
    configure_vip_timer_acceptance(bot_instance)

    configure_acceptance_dispatch_refresh(
        dispatch_channel_id=dispatch_channel_id,
        order_claims=order_claims,
        payment_method_view_type=payment_method_view_type,
        order_selections=order_selections,
    )

    configure_acceptance_sync_worker(
        bot_instance=bot_instance,
        guild_id=guild_id,
        refresh_acceptance_dispatch=refresh_acceptance_dispatch_from_web_order,
        refresh_existing_web_sync_dispatch=refresh_existing_web_sync_dispatch,
        grant_ticket_access=grant_order_ticket_access,
        revoke_ticket_access=revoke_order_ticket_access,
        to_int=_to_int,
    )
    configure_acceptance_repair_runtime(
        order_selections=order_selections,
        payment_method_view_type=payment_method_view_type,
        refresh_acceptance_dispatch=refresh_acceptance_dispatch_from_web_order,
        sync_ticket_access_from_state=sync_acceptance_ticket_access_from_state,
    )


def _apply_acceptance_state_to_claim_data(claim_data: dict, state) -> None:
    """Apply acceptance state, then prefer formal active assignments after payment."""
    _apply_acceptance_state_to_claim_data_base(claim_data, state)

    if str(getattr(state, "status", "") or "").strip().lower() != "active":
        return

    order_id = _to_int(getattr(state, "order_id", None))
    if order_id is None:
        return

    try:
        from sqlalchemy import select
        from shared.db import SessionLocal
        from shared.models import OrderAssignment

        db = SessionLocal()
        try:
            assignments = db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == int(order_id))
                .where(OrderAssignment.is_active.is_(True))
                .order_by(OrderAssignment.id.asc())
            ).all()
        finally:
            db.close()
    except Exception as exc:
        print(
            f"[acceptance] active assignment refresh failed order_id={order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return

    # Legacy active orders may predate formal assignments. Keep their saved
    # acceptance snapshot if there is no canonical assignment row to replace it.
    if not assignments:
        return

    companion_ids: set[int] = set()
    booster_ids: set[int] = set()

    for assignment in assignments:
        worker_id = _to_int(getattr(assignment, "worker_discord_id", None))
        if worker_id is None:
            continue

        role_type = str(getattr(assignment, "role_type", "") or "").strip().lower()
        if role_type == "companion":
            companion_ids.add(worker_id)
        else:
            booster_ids.add(worker_id)

    if not companion_ids and not booster_ids:
        return

    claim_data["companion"] = companion_ids
    claim_data["booster"] = booster_ids


def _member_role_id_texts(member: discord.Member) -> list[str]:
    return [
        str(role.id)
        for role in getattr(member, "roles", [])
        if getattr(role, "id", None) is not None
    ]


def _member_display_name(member: discord.Member) -> str:
    return str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or getattr(member, "id", None)
        or "未知使用者"
    )


# Compatibility export for existing imports while presentation now lives with the
# payment panel lifecycle instead of the orchestration runtime.
_acceptance_staff_display_text = acceptance_staff_display_text
