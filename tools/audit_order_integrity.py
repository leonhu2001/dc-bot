from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))
WEB_DB = Path(os.environ.get("WEB_DB", str(ROOT / "web_dashboard.db")))
BOT_DB = Path(os.environ.get("BOT_DB", str(ROOT / "bot.db")))


OPEN_STATUSES = {"waiting_acceptance", "accepted_pending_pay", "active", "stored"}
FINAL_STATUSES = {"closed", "cancelled", "canceled"}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def sep(index: int | None = None) -> None:
    print("-" * 80)
    if index is not None:
        print(f"#{index}")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def print_rows(title_text: str, rows: list[sqlite3.Row] | list[dict[str, Any]]) -> None:
    title(title_text)
    if not rows:
        print("NONE")
        return

    for i, row in enumerate(rows, 1):
        sep(i)
        data = dict(row)
        for key, value in data.items():
            print(f"{key}: {value}")


def scalar(conn: sqlite3.Connection, sql: str, params: dict[str, Any] | tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def status_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def web_order_status_counts(web: sqlite3.Connection) -> None:
    rows = web.execute("""
        SELECT status, COUNT(*) AS count
        FROM web_orders
        GROUP BY status
        ORDER BY status
    """).fetchall()
    print_rows("WEB_ORDER_STATUS_COUNTS", rows)


def open_orders(web: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = web.execute("""
        SELECT
            id,
            status,
            customer_display_name,
            customer_discord_id,
            category,
            item,
            quantity,
            amount,
            customer_pay_amount,
            payout_base_amount,
            payment_method,
            ticket_channel_id,
            dispatch_channel_id,
            dispatch_message_id,
            created_at,
            updated_at,
            closed_at,
            note
        FROM web_orders
        WHERE LOWER(COALESCE(status, '')) IN ('waiting_acceptance', 'accepted_pending_pay', 'active', 'stored')
        ORDER BY id
    """).fetchall()
    print_rows("OPEN_ORDERS", rows)
    return rows


def open_order_health(web: sqlite3.Connection, open_rows: list[sqlite3.Row]) -> None:
    title("OPEN_ORDER_HEALTH_REPORT")

    if not open_rows:
        print("NONE")
        return

    for i, order in enumerate(open_rows, 1):
        order_id = int(order["id"])
        web_status = status_lower(order["status"])

        meta = web.execute("""
            SELECT *
            FROM order_acceptance_meta
            WHERE order_id = ?
        """, (order_id,)).fetchone()

        meta_status = status_lower(meta["status"] if meta else None)

        claim_count = int(scalar(web, """
            SELECT COUNT(*)
            FROM order_acceptance_claims
            WHERE order_id = ?
              AND COALESCE(is_active, 1) = 1
        """, (order_id,)) or 0)

        assignment_count = int(scalar(web, """
            SELECT COUNT(*)
            FROM order_assignments
            WHERE order_id = ?
              AND COALESCE(is_active, 1) = 1
        """, (order_id,)) or 0)

        worker_payout_count = int(scalar(web, """
            SELECT COUNT(*)
            FROM worker_payouts
            WHERE order_id = ?
        """, (order_id,)) or 0)

        cs_payout_count = int(scalar(web, """
            SELECT COUNT(*)
            FROM customer_service_payouts
            WHERE order_id = ?
        """, (order_id,)) or 0)

        issues: list[str] = []

        if meta is None:
            issues.append("missing_acceptance_meta")
        elif meta_status != web_status:
            issues.append(f"status_mismatch_meta={meta_status}")

        if web_status in {"waiting_acceptance", "accepted_pending_pay"} and claim_count == 0:
            issues.append("prepay_without_claims")

        if web_status == "accepted_pending_pay" and meta is not None:
            required = int(meta["required_staff_count"] or 1)
            if claim_count < required:
                issues.append(f"accepted_pending_pay_claims_lt_required:{claim_count}/{required}")

        if web_status == "active":
            if assignment_count == 0:
                issues.append("active_without_assignment")
            if worker_payout_count == 0 and int(order["amount"] or 0) > 0:
                issues.append("active_without_worker_payout")
            if cs_payout_count == 0 and str(order["customer_discord_id"] or "").strip():
                issues.append("active_without_cs_payout")

        sep(i)
        print(f"order_id: {order_id}")
        print(f"web_status: {web_status}")
        print(f"meta_status: {meta_status or None}")
        print(f"claim_count: {claim_count}")
        print(f"assignment_count: {assignment_count}")
        print(f"worker_payout_count: {worker_payout_count}")
        print(f"cs_payout_count: {cs_payout_count}")
        print(f"issues: {', '.join(issues) if issues else 'OK'}")


def acceptance_integrity(web: sqlite3.Connection) -> None:
    print_rows(
        "ACCEPTANCE_META_WITHOUT_WEB_ORDER",
        web.execute("""
            SELECT m.order_id, m.status
            FROM order_acceptance_meta m
            LEFT JOIN web_orders w ON w.id = m.order_id
            WHERE w.id IS NULL
            ORDER BY m.order_id
        """).fetchall(),
    )

    print_rows(
        "STATUS_MISMATCH_WEB_VS_ACCEPTANCE_META",
        web.execute("""
            SELECT
                w.id,
                w.status AS web_status,
                m.status AS meta_status
            FROM web_orders w
            JOIN order_acceptance_meta m ON m.order_id = w.id
            WHERE LOWER(COALESCE(w.status, '')) != LOWER(COALESCE(m.status, ''))
            ORDER BY w.id
        """).fetchall(),
    )

    print_rows(
        "ACCEPTANCE_CLAIMS_WITHOUT_META",
        web.execute("""
            SELECT c.id, c.order_id, c.staff_discord_id, c.is_active
            FROM order_acceptance_claims c
            LEFT JOIN order_acceptance_meta m ON m.order_id = c.order_id
            WHERE m.order_id IS NULL
            ORDER BY c.id
        """).fetchall(),
    )


def assignment_and_payout_integrity(web: sqlite3.Connection) -> None:
    print_rows(
        "CLOSED_OR_ACTIVE_WITHOUT_ASSIGNMENTS",
        web.execute("""
            SELECT
                w.id,
                w.status,
                w.category,
                w.item,
                w.amount,
                COUNT(a.id) AS assignment_count
            FROM web_orders w
            LEFT JOIN order_assignments a
                ON a.order_id = w.id
               AND COALESCE(a.is_active, 1) = 1
            WHERE LOWER(COALESCE(w.status, '')) IN ('active', 'closed')
            GROUP BY w.id
            HAVING assignment_count = 0
            ORDER BY w.id DESC
        """).fetchall(),
    )

    print_rows(
        "ACTIVE_OR_CLOSED_WITHOUT_WORKER_PAYOUTS_AMOUNT_GT_0",
        web.execute("""
            SELECT
                w.id,
                w.status,
                w.category,
                w.item,
                w.amount,
                w.customer_pay_amount,
                w.payment_method,
                COUNT(p.id) AS worker_payout_count
            FROM web_orders w
            LEFT JOIN worker_payouts p ON p.order_id = w.id
            WHERE LOWER(COALESCE(w.status, '')) IN ('active', 'closed')
              AND COALESCE(w.amount, 0) > 0
            GROUP BY w.id
            HAVING worker_payout_count = 0
            ORDER BY w.id DESC
        """).fetchall(),
    )

    print_rows(
        "ACTIVE_OR_CLOSED_WITHOUT_WORKER_PAYOUTS_AMOUNT_0",
        web.execute("""
            SELECT
                w.id,
                w.status,
                w.category,
                w.item,
                w.amount,
                w.customer_pay_amount,
                w.payment_method,
                COUNT(p.id) AS worker_payout_count
            FROM web_orders w
            LEFT JOIN worker_payouts p ON p.order_id = w.id
            WHERE LOWER(COALESCE(w.status, '')) IN ('active', 'closed')
              AND COALESCE(w.amount, 0) = 0
            GROUP BY w.id
            HAVING worker_payout_count = 0
            ORDER BY w.id DESC
        """).fetchall(),
    )

    print_rows(
        "ACTIVE_OR_CLOSED_WITHOUT_CUSTOMER_SERVICE_PAYOUTS_AMOUNT_GT_0",
        web.execute("""
            SELECT
                w.id,
                w.status,
                w.category,
                w.item,
                w.amount,
                w.customer_pay_amount,
                w.customer_service_discord_id,
                COUNT(csp.id) AS cs_payout_count
            FROM web_orders w
            LEFT JOIN customer_service_payouts csp ON csp.order_id = w.id
            WHERE LOWER(COALESCE(w.status, '')) IN ('active', 'closed')
              AND COALESCE(w.amount, 0) > 0
            GROUP BY w.id
            HAVING cs_payout_count = 0
            ORDER BY w.id DESC
        """).fetchall(),
    )


def sync_events_report(web: sqlite3.Connection) -> None:
    if not table_exists(web, "sync_events"):
        title("SYNC_EVENTS")
        print("TABLE_NOT_FOUND")
        return

    sync_cols = columns(web, "sync_events")
    time_col = "processed_at" if "processed_at" in sync_cols else ("updated_at" if "updated_at" in sync_cols else "created_at")

    print_rows(
        "SYNC_EVENT_STATUS_COUNTS",
        web.execute("""
            SELECT status, event_type, COUNT(*) AS count
            FROM sync_events
            GROUP BY status, event_type
            ORDER BY status, event_type
        """).fetchall(),
    )

    print_rows(
        "RECENT_FAILED_SYNC_EVENTS",
        web.execute(f"""
            SELECT id, event_type, status, order_id, error_message, created_at, {time_col} AS last_time
            FROM sync_events
            WHERE LOWER(COALESCE(status, '')) = 'failed'
            ORDER BY id DESC
            LIMIT 30
        """).fetchall(),
    )


def rule_snapshot_report(web: sqlite3.Connection) -> None:
    web_cols = columns(web, "web_orders")
    meta_cols = columns(web, "order_acceptance_meta")

    required_web = {"order_rule_key", "rule_version", "rule_snapshot_json", "price_snapshot_json"}
    required_meta = {"rule_version", "rule_snapshot_json", "price_snapshot_json"}

    title("RULE_SNAPSHOT_SCHEMA")
    print("web_orders_missing:", ", ".join(sorted(required_web - web_cols)) or "NONE")
    print("order_acceptance_meta_missing:", ", ".join(sorted(required_meta - meta_cols)) or "NONE")

    if required_web <= web_cols:
        print_rows(
            "RECENT_WEB_ORDER_SNAPSHOTS",
            web.execute("""
                SELECT
                    id,
                    status,
                    order_rule_key,
                    rule_version,
                    CASE
                        WHEN rule_snapshot_json IS NULL OR rule_snapshot_json = '' THEN 0
                        ELSE 1
                    END AS has_rule_snapshot,
                    CASE
                        WHEN price_snapshot_json IS NULL OR price_snapshot_json = '' THEN 0
                        ELSE 1
                    END AS has_price_snapshot,
                    created_at
                FROM web_orders
                ORDER BY id DESC
                LIMIT 20
            """).fetchall(),
        )

    if required_meta <= meta_cols:
        print_rows(
            "RECENT_ACCEPTANCE_META_SNAPSHOTS",
            web.execute("""
                SELECT
                    order_id,
                    status,
                    order_rule_key,
                    rule_version,
                    CASE
                        WHEN rule_snapshot_json IS NULL OR rule_snapshot_json = '' THEN 0
                        ELSE 1
                    END AS has_rule_snapshot,
                    CASE
                        WHEN price_snapshot_json IS NULL OR price_snapshot_json = '' THEN 0
                        ELSE 1
                    END AS has_price_snapshot,
                    created_at
                FROM order_acceptance_meta
                ORDER BY order_id DESC
                LIMIT 20
            """).fetchall(),
        )


def bot_claims_report(web: sqlite3.Connection) -> None:
    title("BOT_CLAIMS_HEALTH")

    if not BOT_DB.exists():
        print(f"BOT_DB_NOT_FOUND: {BOT_DB}")
        return

    bot = connect(BOT_DB)

    try:
        if not table_exists(bot, "claims"):
            print("TABLE_NOT_FOUND")
            return

        claims = bot.execute("""
            SELECT dispatch_message_id, source_channel_id, status, locked
            FROM claims
            ORDER BY dispatch_message_id
        """).fetchall()

        web_by_dispatch = {}
        web_by_ticket = {}

        for row in web.execute("""
            SELECT id, status, ticket_channel_id, dispatch_message_id
            FROM web_orders
        """).fetchall():
            data = dict(row)
            if data.get("dispatch_message_id"):
                web_by_dispatch[str(data["dispatch_message_id"])] = data
            if data.get("ticket_channel_id"):
                web_by_ticket[str(data["ticket_channel_id"])] = data

        print("CLAIMS_COUNT:", len(claims))

        if not claims:
            print("NONE")
            return

        bad = []

        for i, row in enumerate(claims, 1):
            data = dict(row)
            dispatch_id = str(data.get("dispatch_message_id") or "")
            ticket_id = str(data.get("source_channel_id") or "")
            linked = web_by_dispatch.get(dispatch_id) or web_by_ticket.get(ticket_id)
            linked_status = status_lower(linked.get("status") if linked else None)

            issue = None
            if linked is None:
                issue = "missing_web_order"
            elif linked_status not in OPEN_STATUSES:
                issue = f"linked_web_order_not_open:{linked_status}"

            sep(i)
            print("claim:", data)
            print("linked_web_order:", linked)
            print("issue:", issue or "OK")

            if issue:
                bad.append((data, linked, issue))

        title("BOT_CLAIMS_ISSUES")
        if not bad:
            print("NONE")
        else:
            for i, (claim, linked, issue) in enumerate(bad, 1):
                sep(i)
                print("claim:", claim)
                print("linked_web_order:", linked)
                print("issue:", issue)

    finally:
        bot.close()


def main() -> None:
    if not WEB_DB.exists():
        raise SystemExit(f"WEB_DB not found: {WEB_DB}")

    web = connect(WEB_DB)

    try:
        title("DB_FILES")
        print("ROOT:", ROOT)
        print("WEB_DB:", WEB_DB)
        print("BOT_DB:", BOT_DB)

        title("DB_TABLES")
        rows = web.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        print(", ".join(row["name"] for row in rows))

        web_order_status_counts(web)
        open_rows = open_orders(web)
        open_order_health(web, open_rows)
        acceptance_integrity(web)
        assignment_and_payout_integrity(web)
        sync_events_report(web)
        rule_snapshot_report(web)
        bot_claims_report(web)

        title("REPORT_DONE")
        print("OK")

    finally:
        web.close()


if __name__ == "__main__":
    main()
