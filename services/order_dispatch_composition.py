from __future__ import annotations

from services.acceptance.runtime import (
    _apply_acceptance_state_to_claim_data,
    _member_display_name,
    _member_role_id_texts,
    send_acceptance_payment_panel_if_ready,
)
from services.order_credential_runtime import (
    _order_requires_credentials,
    revoke_order_credential_messages,
)
from services.order_dispatch_runtime import configure_order_dispatch_runtime_explicit


def configure_order_dispatch_composition(
    booster_receiver_role_id,
    dispatch_channel_id,
    order_claims,
    order_selections,
) -> None:
    """Wire dispatch runtime using only bot-owned state at the composition root."""
    configure_order_dispatch_runtime_explicit(
        booster_receiver_role_id=booster_receiver_role_id,
        dispatch_channel_id=dispatch_channel_id,
        order_claims=order_claims,
        order_selections=order_selections,
        acceptance_state_applier=_apply_acceptance_state_to_claim_data,
        member_display_name=_member_display_name,
        member_role_ids=_member_role_id_texts,
        order_requires_credentials=_order_requires_credentials,
        revoke_credential_messages=revoke_order_credential_messages,
        send_payment_panel=send_acceptance_payment_panel_if_ready,
    )
