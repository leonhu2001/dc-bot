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
    """Return completed-order performance without payroll-transfer effects.

    Performance is the worker payout row's gross earned share attributed to the
    month in which the order was closed. It measures completed-order business
    volume, not the worker's eventual take-home payroll. Commission, payout
    adjustments and internal payroll transfers therefore do not reduce the
    performance number. Tips and customer-service payouts are excluded.

    Older databases that predate ``gross_share`` fall back to ``final_payout`` so
    the dashboard remains usable during migrations.
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

        has_gross_share = _column_exists(conn, "worker_payouts", "gross_share")
        has_final_payout = _column_exists(conn, "worker_payouts", "final_payout")
        if not has_gross_share and not has_final_payout:
            return {}

        performance_sql = (
            "COALESCE(p.gross_share, 0)"
            if has_gross_share
            else "COALESCE(p.final_payout, 0)"
        )

        where = [
            "w.status = 'closed'",
            f"{performance_sql} > 0",
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
                {performance_sql} AS performance_amount
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    totals: dict[str, int] = {}
    for row in rows:
        discord_id = str(row["discord_id"] or "").strip()
        if not discord_id:
            continue
        try:
            amount = int(round(float(row["performance_amount"] or 0)))
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
