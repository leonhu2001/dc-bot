from __future__ import annotations

from core.database import remember_claim_data, remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.acceptance.runtime import _build_receiver_text_from_claim_data
from services.logging_service import send_order_log
from services.order_dispatch_runtime import DispatchClaimView
from services.order_flow import build_payment_method_embed
from services.order_lifecycle_runtime import ensure_payment_submit_receipt
from services.order_payment_runtime import configure_order_payment_runtime
from services.orders import ORDER_CATEGORY_LABELS, _to_int, build_self_service_order_embed
from services.rewards import add_customer_reward_from_order, fetch_member_safely, format_t_amount
from services.ticket_identity import rename_ticket_channel
from services.wallet_discord_runtime import adjust_customer_wallet_balance, send_wallet_log


def configure_order_payment_composition(
    dispatch_channel_id,
    order_claims,
    order_selections,
    staff_order_operation_view,
) -> None:
    """Wire payment runtime using bot-owned state only."""
    # PaymentMethodView still lives in the transitional order UI module. Import it
    # lazily so composition does not create an import cycle during module startup.
    from services.order_runtime import PaymentMethodView

    configure_order_payment_runtime(
        dispatch_channel_id=dispatch_channel_id,
        dispatch_claim_view=DispatchClaimView,
        order_category_labels=ORDER_CATEGORY_LABELS,
        order_claims=order_claims,
        payment_method_view=PaymentMethodView,
        self_service_order_selections=order_selections,
        staff_order_operation_view=staff_order_operation_view,
        receiver_text_builder=_build_receiver_text_from_claim_data,
        to_int=_to_int,
        customer_reward_adder=add_customer_reward_from_order,
        wallet_adjuster=adjust_customer_wallet_balance,
        payment_method_embed_builder=build_payment_method_embed,
        self_service_order_embed_builder=build_self_service_order_embed,
        payment_receipt_ensurer=ensure_payment_submit_receipt,
        fetch_member=fetch_member_safely,
        amount_formatter=format_t_amount,
        taipei_now_iso=get_taipei_now_iso,
        remember_claim=remember_claim_data,
        remember_order=remember_order_data,
        ticket_channel_renamer=rename_ticket_channel,
        save_data=save_bot_data,
        order_log_sender=send_order_log,
        wallet_log_sender=send_wallet_log,
    )
