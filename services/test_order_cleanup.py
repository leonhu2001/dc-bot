from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text


REPAIR_TABLE = "one_time_data_repairs"
REPAIR_KEY = "2026-10-12:purge-roulette-test-orders-12001-12002-v1"
TARGET_ORDER_NOS = ("MO20261012001", "MO20261012002")
ROULETTE_RULE_KEY = "admin_delta_desktop_fun_20261007053129_91eb"

# Operational rows that are safe to remove together with these explicitly
# authorised test orders. Wallet/payment ledger rows are intentionally NOT here:
# accounting history must remain intact even when the test order is removed from
# normal order/KPI reporting.
ORDER_CHILD_TABLES = (
    "roulette_draw_history",
    "roulette_redraw_grants",
    "roulette_redraw_credits",
    "roulette_ready_notifications",
    "roulette_draws",
    "order_acceptance_claims",
    "order_acceptance_meta",
    "order_cancellations",
    "order_state_history",
    "order_assignments",
    "worker_payouts",
    "worker_payout_overrides",
    "customer_service_payouts",
    "sync_events",
)


def _ensure_repair_table(conn) -> None:
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {REPAIR_TABLE} (
                repair_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                note TEXT
            )
            """
        )
    )


def purge_authorized_test_orders(bind) -> dict[str, Any]:
    """Remove the two 2026-10-12 roulette test orders from operational data.

    The owner explicitly authorised deletion of these exact order numbers.  The
    cleanup is deliberately narrow: only cancelled roulette orders matching the
    exact numbers can be deleted, while wallet/payment ledger history is kept.
    A repair marker makes the operation idempotent on future deploys.
    """

    with bind.begin() as conn:
        _ensure_repair_table(conn)

        already = conn.execute(
            text(
                f"SELECT 1 FROM {REPAIR_TABLE} "
                "WHERE repair_key = :repair_key LIMIT 1"
            ),
            {"repair_key": REPAIR_KEY},
        ).first()
        if already is not None:
            return {"status": "already_applied", "repair_key": REPAIR_KEY}

        rows = conn.execute(
            text(
                """
                SELECT id, bot_order_no, status, item, order_rule_key
                FROM web_orders
                WHERE bot_order_no IN (:order_no_1, :order_no_2)
                ORDER BY id ASC
                """
            ),
            {
                "order_no_1": TARGET_ORDER_NOS[0],
                "order_no_2": TARGET_ORDER_NOS[1],
            },
        ).mappings().all()

        invalid: list[dict[str, Any]] = []
        for row in rows:
            status = str(row.get("status") or "").strip().lower()
            rule_key = str(row.get("order_rule_key") or "").strip()
            item = str(row.get("item") or "")
            if status not in {"cancelled", "canceled"}:
                invalid.append({"order_no": row.get("bot_order_no"), "reason": "not cancelled"})
                continue
            if rule_key != ROULETTE_RULE_KEY and "俄羅斯輪盤" not in item:
                invalid.append({"order_no": row.get("bot_order_no"), "reason": "not roulette"})

        # Fail closed. If a target number has somehow been reused or reopened,
        # delete nothing and allow a later deploy to retry after manual review.
        if invalid:
            return {
                "status": "skipped",
                "repair_key": REPAIR_KEY,
                "reason": json.dumps(invalid, ensure_ascii=False),
            }

        existing_tables = set(inspect(conn).get_table_names())
        deleted_orders: list[dict[str, Any]] = []

        for row in rows:
            order_id = int(row["id"])
            order_no = str(row["bot_order_no"])

            for table_name in ORDER_CHILD_TABLES:
                if table_name not in existing_tables:
                    continue
                conn.execute(
                    text(f'DELETE FROM "{table_name}" WHERE order_id = :order_id'),
                    {"order_id": order_id},
                )

            conn.execute(
                text("DELETE FROM web_orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            deleted_orders.append({"id": order_id, "order_no": order_no})

        # Keep a non-KPI audit trace. This table is intentionally not tied to
        # web_orders with a foreign key, so the deletion itself remains auditable.
        if "admin_audit_logs" in existing_tables:
            now = datetime.utcnow()
            for deleted in deleted_orders:
                conn.execute(
                    text(
                        """
                        INSERT INTO admin_audit_logs (
                            admin_discord_id,
                            action,
                            target_type,
                            target_id,
                            before_json,
                            after_json,
                            created_at
                        )
                        VALUES (
                            'system',
                            'purge_authorized_test_order',
                            'order',
                            :target_id,
                            :before_json,
                            :after_json,
                            :created_at
                        )
                        """
                    ),
                    {
                        "target_id": deleted["order_no"],
                        "before_json": json.dumps(deleted, ensure_ascii=False),
                        "after_json": json.dumps(
                            {"deleted": True, "reason": "owner-authorised roulette test order cleanup"},
                            ensure_ascii=False,
                        ),
                        "created_at": now,
                    },
                )

        applied_at = datetime.utcnow().isoformat(timespec="seconds")
        conn.execute(
            text(
                f"""
                INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note)
                VALUES (:repair_key, :applied_at, :note)
                """
            ),
            {
                "repair_key": REPAIR_KEY,
                "applied_at": applied_at,
                "note": (
                    "Purged authorised roulette test orders: "
                    + ", ".join(item["order_no"] for item in deleted_orders)
                    if deleted_orders
                    else "Authorised roulette test orders were already absent."
                ),
            },
        )

        return {
            "status": "applied" if deleted_orders else "already_clean",
            "repair_key": REPAIR_KEY,
            "deleted": deleted_orders,
        }
