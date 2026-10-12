from __future__ import annotations

from core.time_utils import utc_now_naive
import json
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text


REPAIR_TABLE = "one_time_data_repairs"
REPAIR_KEY = "2026-10-12:purge-roulette-test-orders-12001-12002-v2"
TARGET_ORDER_NOS = ("MO20261012001", "MO20261012002")
ROULETTE_RULE_KEY = "admin_delta_desktop_fun_20261007053129_91eb"

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
    """Remove only the two owner-authorised cancelled roulette test orders.

    Wallet/payment ledger rows are deliberately preserved. The operation is
    fail-closed and idempotent so future deploys cannot delete unrelated data.
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
                invalid.append(
                    {
                        "order_no": row.get("bot_order_no"),
                        "reason": "not cancelled",
                    }
                )
                continue
            if rule_key != ROULETTE_RULE_KEY and "俄羅斯輪盤" not in item:
                invalid.append(
                    {
                        "order_no": row.get("bot_order_no"),
                        "reason": "not roulette",
                    }
                )

        if invalid:
            return {
                "status": "skipped",
                "repair_key": REPAIR_KEY,
                "reason": json.dumps(invalid, ensure_ascii=False),
            }

        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        table_columns = {
            table: {str(col["name"]) for col in inspector.get_columns(table)}
            for table in ORDER_CHILD_TABLES
            if table in table_names
        }
        deleted_orders: list[dict[str, Any]] = []

        for row in rows:
            order_id = int(row["id"])
            order_no = str(row["bot_order_no"])

            for table_name, columns in table_columns.items():
                if "order_id" not in columns:
                    continue
                conn.execute(
                    text(
                        f'DELETE FROM "{table_name}" '
                        "WHERE order_id = :order_id"
                    ),
                    {"order_id": order_id},
                )

            conn.execute(
                text("DELETE FROM web_orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            deleted_orders.append({"id": order_id, "order_no": order_no})

        if "admin_audit_logs" in table_names and deleted_orders:
            audit_columns = {
                str(col["name"])
                for col in inspector.get_columns("admin_audit_logs")
            }
            required = {
                "admin_discord_id",
                "action",
                "target_type",
                "target_id",
                "before_json",
                "after_json",
                "created_at",
            }
            if required.issubset(audit_columns):
                now = utc_now_naive()
                for deleted in deleted_orders:
                    conn.execute(
                        text(
                            """
                            INSERT INTO admin_audit_logs (
                                admin_discord_id, action, target_type, target_id,
                                before_json, after_json, created_at
                            ) VALUES (
                                'system', 'purge_authorized_test_order', 'order',
                                :target_id, :before_json, :after_json, :created_at
                            )
                            """
                        ),
                        {
                            "target_id": deleted["order_no"],
                            "before_json": json.dumps(
                                deleted,
                                ensure_ascii=False,
                            ),
                            "after_json": json.dumps(
                                {
                                    "deleted": True,
                                    "reason": (
                                        "owner-authorised roulette test order cleanup"
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                            "created_at": now,
                        },
                    )

        applied_at = utc_now_naive().isoformat(timespec="seconds")
        note = (
            "Purged authorised roulette test orders: "
            + ", ".join(item["order_no"] for item in deleted_orders)
            if deleted_orders
            else "Authorised roulette test orders were already absent."
        )
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
                "note": note,
            },
        )

        return {
            "status": "applied" if deleted_orders else "already_clean",
            "repair_key": REPAIR_KEY,
            "deleted": deleted_orders,
        }
