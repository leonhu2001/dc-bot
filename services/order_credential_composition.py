from __future__ import annotations

from core.database import remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.order_credential_runtime import configure_order_credentials
from services.orders import _to_int
from services.rewards import fetch_member_safely


def configure_order_credential_composition(
    credential_owner_user_id,
    guild_id,
    order_selections,
    bot_instance,
) -> None:
    """Wire credential runtime using bot-owned state only."""
    configure_order_credentials(
        credential_owner_user_id=credential_owner_user_id,
        guild_id=guild_id,
        self_service_order_selections=order_selections,
        to_int=_to_int,
        bot_instance=bot_instance,
        fetch_member=fetch_member_safely,
        taipei_now_iso=get_taipei_now_iso,
        remember_data=remember_order_data,
        save_data=save_bot_data,
    )
