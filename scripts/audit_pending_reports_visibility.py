#!/usr/bin/env python3
"""Read-only visibility and notification audit for submitted order reports.

No services are restarted. No SQL INSERT/UPDATE/DELETE/DDL and no Discord posts.
Run on the VPS after deploying this script:
  ./venv/bin/python scripts/audit_pending_reports_visibility.py
Optionally provide --db /absolute/path/to/web_dashboard.db.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def audit(db_file: Path) -> dict[str, object]:
    if not db_file.is_file():
        raise FileNotFoundError(f"Database not found: {db_file}")
    uri = db_file.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")  # A consistent read-only snapshot.
        for table in ("web_orders", "order_reports"):
            if not _table_exists(conn, table):
                raise RuntimeError(f"Required table missing: {table}")
        pending_rows = [
            dict(row) for row in conn.execute("""
                SELECT r.id AS report_id, r.order_id, r.submitted_at,
                       o.id AS parent_id, o.status AS order_status
                FROM order_reports r
                LEFT JOIN web_orders o ON o.id = r.order_id
                WHERE r.status = 'pending'
                ORDER BY COALESCE(r.submitted_at, r.updated_at) DESC, r.id DESC
            """)
        ]
        closed_ids = {
            int(row["order_id"]) for row in pending_rows
            if str(row["order_status"] or "").strip().lower() == "closed"
        }
        not_closed = [
            row for row in pending_rows
            if row["parent_id"] is not None
            and str(row["order_status"] or "").strip().lower() != "closed"
        ]
        missing_parent = [
            row for row in pending_rows if row["parent_id"] is None
        ]

        # Reconstruct the previous/default top-250 behavior to identify
        # submitted reports that were pushed out by missing-report priority.
        old_first_page = {
            int(row["id"]) for row in conn.execute("""
                SELECT o.id
                FROM web_orders o
                LEFT JOIN order_reports r ON r.order_id = o.id
                WHERE LOWER(TRIM(COALESCE(o.status, ''))) = 'closed'
                  AND COALESCE(r.status, 'approved')
                      IN ('missing','pending','changes_requested')
                ORDER BY CASE COALESCE(r.status, 'approved')
                    WHEN 'missing' THEN 0 WHEN 'pending' THEN 1
                    WHEN 'changes_requested' THEN 2 ELSE 3 END,
                    COALESCE(o.closed_at, o.updated_at, o.created_at) DESC,
                    o.id DESC
                LIMIT 250
            """)
        }
        pushed_out = closed_ids - old_first_page

        notice_states = Counter()
        notice_issues = []
        if _table_exists(conn, "order_report_review_notifications"):
            rows = conn.execute("""
                SELECT r.order_id, n.status AS notice_status,
                       n.attempts
                FROM order_reports r
                LEFT JOIN order_report_review_notifications n
                  ON n.report_id = r.id
                 AND n.submitted_at = r.submitted_at
                WHERE r.status = 'pending'
            """)
            for item in rows:
                order_id, status, attempts = (
                    int(item["order_id"]),
                    str(item["notice_status"] or "missing"),
                    int(item["attempts"] or 0),
                )
                key = (
                    "retries_exhausted" if status in ("failed", "pending")
                    and attempts >= 5 else status
                )
                notice_states[key] += 1
                if key in ("missing", "retries_exhausted", "failed", "processing"):
                    notice_issues.append((order_id, key, attempts))
        else:
            notice_states["table_missing"] = len(pending_rows)

        return {
            "pending_total": len(pending_rows),
            "pending_closed": len(closed_ids),
            "pending_nonclosed": len(not_closed),
            "pending_no_order": len(missing_parent),
            "old_default_page_excluded_pending": len(pushed_out),
            "old_default_page_excluded_ids": sorted(pushed_out)[:30],
            "nonclosed_ids_and_states": [
                (int(row["order_id"]), str(row["order_status"] or ""))
                for row in not_closed[:30]
            ],
            "no_order_ids": [int(row["order_id"]) for row in missing_parent[:30]],
            "notice_states": dict(sorted(notice_states.items())),
            "notice_problem_ids": notice_issues[:30],
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path,
        default=Path(__file__).resolve().parents[1] / "web_dashboard.db",
    )
    args = parser.parse_args()
    result = audit(args.db)
    for key, value in result.items():
        print(f"{key}: {value}")
    print("READ_ONLY_AUDIT_COMPLETE (no database or service changes)")


if __name__ == "__main__":
    main()
