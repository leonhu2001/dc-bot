from __future__ import annotations


ADMIN_BASE_URL = "https://mowanentertainment.com"


def admin_order_workspace_url(order_id: int | str) -> str:
    parsed = int(order_id)
    if parsed <= 0:
        raise ValueError("order_id must be positive")
    return f"{ADMIN_BASE_URL}/admin/order-workspace/{parsed}"


def build_cs_review_alert_text(order_id: int | str, role_id: int | None) -> str:
    """Build the one-time actionable CS alert for a new website order."""
    order_number = int(order_id)
    prefix = f"<@&{int(role_id)}>｜" if role_id else ""
    return f"{prefix}WEB-{order_number} 有新訂單需要客服確認。"
