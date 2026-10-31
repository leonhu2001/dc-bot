from __future__ import annotations

import sqlite3
from collections.abc import Iterable


MONTHLY_PERFORMANCE_TARGET = 5000


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table),),
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(
        str(row[1]) == str(column)
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def build_worker_performance_map(
    db_file: str,
    *,
    month: str = "",
    employee_ids: Iterable[str] | None = None,
) -> dict[str, int]:
    """Return earned worker wages, including paid chicken-leg tips.

    Performance is based on completed orders in the order closing month. It
    includes the worker's ``final_payout`` plus paid ``worker_tips.amount``.
    Payroll/internal-transfer adjustments are deliberately excluded, so moving
    salary between employees or into a wallet never creates or destroys earned
    performance.
    """

    ids = {
        str(value or "").strip()
        for value in (employee_ids or [])
        if str(value or "").strip()
    }
    month = str(month or "").strip()

    try:
        conn = sqlite3.connect(str(db_file), timeout=5)
    except sqlite3.Error:
        return {}

    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "worker_payouts") or not _table_exists(conn, "web_orders"):
            return {}
        if not _column_exists(conn, "worker_payouts", "final_payout"):
            return {}

        where = [
            "w.status = 'closed'",
            "COALESCE(p.final_payout, 0) > 0",
            "COALESCE(p.worker_discord_id, '') <> ''",
        ]
        params: list[str] = []

        if month:
            where.append(
                "substr(COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), "
                "NULLIF(w.created_at, '')), 1, 7) = ?"
            )
            params.append(month)

        if ids:
            placeholders = ",".join("?" for _ in ids)
            where.append(f"CAST(p.worker_discord_id AS TEXT) IN ({placeholders})")
            params.extend(sorted(ids))

        rows = conn.execute(
            f"""
            SELECT
                CAST(p.worker_discord_id AS TEXT) AS discord_id,
                COALESCE(p.final_payout, 0) AS amount
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()

        tip_rows = []
        if _table_exists(conn, "worker_tips") and _column_exists(conn, "worker_tips", "amount"):
            tip_where = [
                "w.status = 'closed'",
                "p.payment_status = 'paid'",
                "COALESCE(p.amount, 0) > 0",
                "COALESCE(p.worker_discord_id, '') <> ''",
            ]
            tip_params: list[str] = []
            if month:
                tip_where.append(
                    "substr(COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), "
                    "NULLIF(w.created_at, '')), 1, 7) = ?"
                )
                tip_params.append(month)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                tip_where.append(f"CAST(p.worker_discord_id AS TEXT) IN ({placeholders})")
                tip_params.extend(sorted(ids))
            tip_rows = conn.execute(
                f"""
                SELECT
                    CAST(p.worker_discord_id AS TEXT) AS discord_id,
                    COALESCE(p.amount, 0) AS amount
                FROM worker_tips p
                JOIN web_orders w ON w.id = p.order_id
                WHERE {' AND '.join(tip_where)}
                """,
                tip_params,
            ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    totals: dict[str, int] = {}
    for row in [*rows, *tip_rows]:
        discord_id = str(row["discord_id"] or "").strip()
        if not discord_id:
            continue
        try:
            amount = int(round(float(row["amount"] or 0)))
        except (TypeError, ValueError):
            amount = 0
        totals[discord_id] = int(totals.get(discord_id, 0)) + amount
    return totals


def performance_progress(amount: int, *, target: int = MONTHLY_PERFORMANCE_TARGET) -> dict[str, int | bool]:
    amount = max(0, int(amount or 0))
    target = max(1, int(target or MONTHLY_PERFORMANCE_TARGET))
    return {
        "amount": amount,
        "target": target,
        "reached": amount >= target,
        "remaining": max(0, target - amount),
    }


__all__ = [
    "MONTHLY_PERFORMANCE_TARGET",
    "build_worker_performance_map",
    "performance_progress",
]
