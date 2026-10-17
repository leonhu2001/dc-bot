from __future__ import annotations

from core.database import remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.logging_service import send_order_log
from services.order_dispatch_composition import configure_order_dispatch_composition
from services.order_point_redemption import configure_order_point_redemption
from services.orders import _to_int
from services.rewards import get_current_reward_points, get_customer_reward_data
from services.self_service_financials import get_order_point_item


def configure_order_children(
    booster_receiver_role_id,
    dispatch_channel_id,
    order_claims,
    order_selections,
    customer_rewards,
) -> None:
    """Wire extracted order child runtimes from bot-owned state only."""
    configure_order_dispatch_composition(
        booster_receiver_role_id,
        dispatch_channel_id,
        order_claims,
        order_selections,
    )
    configure_order_point_redemption(
        customer_rewards=customer_rewards,
        to_int=_to_int,
        current_reward_points=get_current_reward_points,
        customer_reward_data=get_customer_reward_data,
        order_point_item=get_order_point_item,
        taipei_now_iso=get_taipei_now_iso,
        remember_data=remember_order_data,
        save_data=save_bot_data,
        order_log_sender=send_order_log,
    )
