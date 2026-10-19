from __future__ import annotations

from sqlalchemy import text

from web.app.services.admin_order_workspace_data import (
    _mw4a2r6_ensure_meta_table,
    _mw4a2r6_user_name,
)


def _order_exists(db, order_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM web_orders
            WHERE id = :order_id
            LIMIT 1
            """
        ),
        {"order_id": int(order_id)},
    ).fetchone()
    return row is not None


def save_order_internal_note(
    db,
    *,
    order_id: int,
    internal_note: str,
    admin_user,
) -> bool:
    if not _order_exists(db, int(order_id)):
        return False

    _mw4a2r6_ensure_meta_table(db)
    db.execute(
        text(
            """
            INSERT INTO web_admin_order_meta (
                order_id,
                internal_note,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            )
            VALUES (
                :order_id,
                :internal_note,
                :updated_by_discord_id,
                :updated_by_display_name,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(order_id)
            DO UPDATE SET
                internal_note = excluded.internal_note,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "order_id": int(order_id),
            "internal_note": str(internal_note or ""),
            "updated_by_discord_id": str(admin_user.get("id") or ""),
            "updated_by_display_name": _mw4a2r6_user_name(admin_user),
        },
    )
    return True


def save_order_attention(
    db,
    *,
    order_id: int,
    needs_attention: bool,
    attention_reason: str,
    admin_user,
) -> bool:
    if not _order_exists(db, int(order_id)):
        return False

    _mw4a2r6_ensure_meta_table(db)
    db.execute(
        text(
            """
            INSERT INTO web_admin_order_meta (
                order_id,
                needs_attention,
                attention_reason,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            )
            VALUES (
                :order_id,
                :needs_attention,
                :attention_reason,
                :updated_by_discord_id,
                :updated_by_display_name,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(order_id)
            DO UPDATE SET
                needs_attention = excluded.needs_attention,
                attention_reason = excluded.attention_reason,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "order_id": int(order_id),
            "needs_attention": 1 if needs_attention else 0,
            "attention_reason": str(attention_reason or ""),
            "updated_by_discord_id": str(admin_user.get("id") or ""),
            "updated_by_display_name": _mw4a2r6_user_name(admin_user),
        },
    )
    return True
