from __future__ import annotations

from core.database import (
    delete_claim_row_from_db,
    remember_claim_data,
    remember_order_data,
    save_bot_data,
)
from core.time_utils import get_taipei_now_iso
from services.acceptance.runtime import _apply_acceptance_state_to_claim_data
from services.order_dispatch_runtime import DispatchClaimView, sync_web_order_status_from_bot
from services.order_storage_runtime import configure_order_storage_runtime
from services.orders import ORDER_CATEGORY_LABELS, _to_int, build_self_service_order_embed
from services.smart_dispatch import set_specified_dm_results
from views.smart_dispatch import (
    prepare_initial_smart_dispatch,
    send_initial_smart_dispatch_alert,
    send_specified_staff_dispatch_dms,
)


def configure_order_storage_composition(
    dispatch_channel_id,
    order_claims,
    order_selections,
) -> None:
    """Wire storage runtime using bot-owned state only."""
    # self_service_runtime still depends on the transitional order_runtime module,
    # so import its rule getter lazily after startup imports are complete.
    from services.self_service_runtime import _get_rule_from_self_service_data

    configure_order_storage_runtime(
        dispatch_channel_id=dispatch_channel_id,
        dispatch_claim_view=DispatchClaimView,
        order_category_labels=ORDER_CATEGORY_LABELS,
        order_claims=order_claims,
        self_service_order_selections=order_selections,
        to_int=_to_int,
        self_service_order_embed_builder=build_self_service_order_embed,
        taipei_now_iso=get_taipei_now_iso,
        remember_claim=remember_claim_data,
        remember_order=remember_order_data,
        save_data=save_bot_data,
        acceptance_state_applier=_apply_acceptance_state_to_claim_data,
        self_service_rule_getter=_get_rule_from_self_service_data,
        claim_row_deleter=delete_claim_row_from_db,
        initial_dispatch_preparer=prepare_initial_smart_dispatch,
        initial_dispatch_alert_sender=send_initial_smart_dispatch_alert,
        specified_staff_dm_sender=send_specified_staff_dispatch_dms,
        specified_dm_result_setter=set_specified_dm_results,
        web_order_status_syncer=sync_web_order_status_from_bot,
    )
