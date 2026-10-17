from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from services.order_close_panel_recovery import is_order_already_closed


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def restore_persistent_review_views(
    bot,
    order_selections: Mapping[int, dict[str, Any]],
    review_view_factory: Callable[..., Any],
    order_summary_getter: Callable[[int], tuple[str | None, str | None]],
) -> int:
    """Re-register saved post-close review panels after a bot restart."""
    restored = 0
    registered_message_ids: set[int] = set()

    for raw_channel_id, order_data in order_selections.items():
        if not isinstance(order_data, dict) or not is_order_already_closed(order_data):
            continue

        channel_id = _to_int(raw_channel_id)
        customer_id = _to_int(order_data.get("customer_id"))
        message_id = _to_int(order_data.get("post_close_panel_message_id"))
        if channel_id is None or customer_id is None or message_id is None:
            continue
        if message_id in registered_message_ids:
            continue

        try:
            order_content, _payment_method = order_summary_getter(channel_id)
        except Exception:
            order_content = None

        try:
            bot.add_view(
                review_view_factory(
                    customer_id=customer_id,
                    order_content=order_content,
                ),
                message_id=message_id,
            )
        except ValueError:
            continue

        registered_message_ids.add(message_id)
        restored += 1

    return restored
