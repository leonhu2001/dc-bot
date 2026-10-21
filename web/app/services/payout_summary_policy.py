from __future__ import annotations

import sqlite3
from typing import Any

from web.app.services.worker_performance import build_worker_performance_map


_WORKER_ROLE_TEXTS = {
    "護航 / 陪玩",
    "護航/陪玩",
    "護航",
    "打手",
    "陪玩",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table),),
        ).fetchone()
        is not None
    )


def _role_keys_from_row(row: dict[str, Any]) -> set[str]:
    role = str(row.get("role") or "").strip()
    if role == "worker":
        return {"worker"}
    if role == "customer_service":
        return {"customer_service"}
    if role == "all":
        # On the existing payout page `all` is the mixed worker + CS identity.
        return {"worker", "customer_service"}

    label = str(row.get("role_label") or "").strip()
    keys: set[str] = set()
    if label in _WORKER_ROLE_TEXTS or "陪玩" in label or "護航" in label or "打手" in label:
        keys.add("worker")
    if "客服" in label:
        keys.add("customer_service")
    return keys


def _role_view(role_keys: set[str]) -> tuple[str, str]:
    has_worker = "worker" in role_keys
    has_customer_service = "customer_service" in role_keys
    if has_worker and has_customer_service:
        return "all", "陪玩/客服"
    if has_worker:
        return "worker", "陪玩"
    if has_customer_service:
        return "customer_service", "客服"
    return "all", "人員"


def _staff_identity_map(db_file: str, employee_ids: set[str]) -> dict[str, set[str]]:
    if not employee_ids:
        return {}
    try:
        conn = sqlite3.connect(str(db_file), timeout=5)
    except sqlite3.Error:
        return {}
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "web_staff_members"):
            return {}
        placeholders = ",".join("?" for _ in employee_ids)
        rows = conn.execute(
            f"""
            SELECT
                CAST(discord_id AS TEXT) AS discord_id,
                COALESCE(is_worker, 0) AS is_worker,
                COALESCE(is_companion, 0) AS is_companion,
                COALESCE(is_customer_service, 0) AS is_customer_service
            FROM web_staff_members
            WHERE CAST(discord_id AS TEXT) IN ({placeholders})
            """,
            sorted(employee_ids),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    result: dict[str, set[str]] = {}
    for row in rows:
        keys: set[str] = set()
        if int(row["is_worker"] or 0) or int(row["is_companion"] or 0):
            keys.add("worker")
        if int(row["is_customer_service"] or 0):
            keys.add("customer_service")
        if keys:
            result[str(row["discord_id"])] = keys
    return result


def _normalize_detail_roles(row: dict[str, Any]) -> None:
    for item in list(row.get("items") or []):
        role_text = str(item.get("role") or "").strip()
        if role_text in _WORKER_ROLE_TEXTS:
            item["role"] = "陪玩"
        elif role_text in {"混合", "總控 / 客服 / 護航", "客服 / 護航", "護航 / 客服"}:
            item["role"] = "陪玩/客服"


def enrich_payout_rows(
    rows: list[dict[str, Any]],
    *,
    db_file: str,
    month: str = "",
) -> list[dict[str, Any]]:
    employee_ids = {
        str(row.get("discord_id") or "").strip()
        for row in rows
        if str(row.get("discord_id") or "").strip()
    }
    performance = build_worker_performance_map(
        db_file,
        month=str(month or ""),
        employee_ids=employee_ids,
    )
    identities = _staff_identity_map(db_file, employee_ids)

    for row in rows:
        discord_id = str(row.get("discord_id") or "").strip()
        row["performance_total"] = int(performance.get(discord_id, 0))
        role_keys = identities.get(discord_id) or _role_keys_from_row(row)
        row["role"], row["role_label"] = _role_view(set(role_keys))
        _normalize_detail_roles(row)
    return rows


def merge_summary_rows(
    unpaid_rows: list[dict[str, Any]],
    paid_rows: list[dict[str, Any]],
    locked_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge the same Discord user into one payroll row across all identities.

    The old page keyed rows by ``(role, discord_id)``. A dual-role employee could
    therefore appear twice when their companion wage was in one payout state and
    their CS wage in another. This merger uses Discord ID as the person key and
    keeps all companion/CS salary items in the same row.
    """

    combined: dict[str, dict[str, Any]] = {}
    for source_rows in (unpaid_rows, locked_rows or [], paid_rows):
        for source in source_rows:
            discord_id = str(source.get("discord_id") or "").strip()
            if not discord_id:
                continue
            item = combined.setdefault(
                discord_id,
                {
                    "discord_id": discord_id,
                    "display_name": str(source.get("display_name") or discord_id),
                    "role_keys": set(),
                    "unpaid_total": 0,
                    "unpaid_count": 0,
                    "locked_total": 0,
                    "locked_count": 0,
                    "paid_total": 0,
                    "paid_count": 0,
                    "performance_total": 0,
                    "items": [],
                },
            )
            display_name = str(source.get("display_name") or "").strip()
            if display_name and item["display_name"] == discord_id:
                item["display_name"] = display_name

            item["role_keys"].update(_role_keys_from_row(source))
            for field in (
                "unpaid_total",
                "unpaid_count",
                "locked_total",
                "locked_count",
                "paid_total",
                "paid_count",
            ):
                item[field] += int(source.get(field) or 0)

            # fetch_rows enriches every status view with the same month-wide
            # performance total, so take max rather than summing it 2–3 times.
            item["performance_total"] = max(
                int(item.get("performance_total") or 0),
                int(source.get("performance_total") or 0),
            )
            item["items"].extend(list(source.get("items") or []))

    result: list[dict[str, Any]] = []
    for row in combined.values():
        role_keys = set(row.pop("role_keys", set()))
        row["role"], row["role_label"] = _role_view(role_keys)
        row["total_count"] = (
            int(row["unpaid_count"] or 0)
            + int(row["locked_count"] or 0)
            + int(row["paid_count"] or 0)
        )
        if row["locked_count"]:
            row["summary_status"] = (
                "部分待報單"
                if row["unpaid_count"] or row["paid_count"]
                else "待報單"
            )
            row["summary_status_class"] = "unpaid"
        elif row["unpaid_count"] and row["paid_count"]:
            row["summary_status"] = "部分待發放"
            row["summary_status_class"] = "partial"
        elif row["unpaid_count"]:
            row["summary_status"] = "待發放"
            row["summary_status_class"] = "unpaid"
        else:
            row["summary_status"] = "正常"
            row["summary_status_class"] = "paid"

        _normalize_detail_roles(row)
        row["items"].sort(
            key=lambda detail: (
                str(detail.get("closed_date") or ""),
                str(detail.get("order_no") or ""),
            ),
            reverse=True,
        )
        result.append(row)

    return sorted(
        result,
        key=lambda row: (
            -(
                int(row.get("unpaid_total") or 0)
                + int(row.get("locked_total") or 0)
                + int(row.get("paid_total") or 0)
            ),
            str(row.get("display_name") or ""),
        ),
    )


def install_payout_summary_policy() -> None:
    from web.app.routers import admin_payout_summary as module

    if getattr(module, "_performance_role_policy_installed", False):
        return

    original_fetch_rows = module.fetch_rows

    def fetch_rows(month, role, q, status="unpaid"):
        rows, totals = original_fetch_rows(month, role, q, status)
        enrich_payout_rows(rows, db_file=module.db_path(), month=str(month or ""))
        return rows, totals

    module.fetch_rows = fetch_rows
    module.build_combined_summary_rows = merge_summary_rows
    module._performance_role_policy_installed = True


__all__ = [
    "enrich_payout_rows",
    "install_payout_summary_policy",
    "merge_summary_rows",
]
