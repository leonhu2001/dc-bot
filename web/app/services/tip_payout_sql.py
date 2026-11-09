"""SQL expressions for both order-linked and stand-alone chicken-leg tips.

A profile tip deliberately has no order_id. Never turn its NULL order_id into
a fabricated Web order: aggregate it as an independent paid-tip salary entry.
"""

TIP_DATE_SQL = """
CASE WHEN p.order_id IS NULL THEN
    COALESCE(NULLIF(p.paid_at, ''), NULLIF(p.created_at, ''))
ELSE
    COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, ''))
END
""".strip()

TIP_ELIGIBLE_SQL = "(p.order_id IS NULL OR w.status = 'closed')"
TIP_ORDER_NO_SQL = (
    "CASE WHEN p.order_id IS NULL THEN 'TIP-' || p.id "
    "ELSE COALESCE(NULLIF(w.bot_order_no,''), 'WEB-' || w.id) END"
)
TIP_CATEGORY_SQL = "CASE WHEN p.order_id IS NULL THEN '雞腿' ELSE w.category END"
TIP_ITEM_SQL = "CASE WHEN p.order_id IS NULL THEN '名片加雞腿' ELSE w.item END"
TIP_CUSTOMER_SQL = (
    "COALESCE(NULLIF(p.customer_display_name,''),"
    " NULLIF(w.customer_display_name,''),"
    " NULLIF(p.customer_discord_id,''),"
    " NULLIF(w.customer_discord_id,''), '未紀錄')"
)


def tip_month_filter(month: str | None) -> tuple[str, list[str]]:
    value = str(month or "").strip()
    if not value:
        return "", []
    return f" AND substr({TIP_DATE_SQL}, 1, 7) = ? ", [value]


def ensure_tip_salary_columns(conn) -> None:
    """Forward-only migration for older tip tables created by salary modules."""
    existing = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(worker_tips)")
    }
    for column in ("created_at", "paid_at", "customer_discord_id",
                   "customer_display_name"):
        if column not in existing:
            conn.execute(f"ALTER TABLE worker_tips ADD COLUMN {column} TEXT")
