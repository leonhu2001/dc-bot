from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from web.app.services.audit_trail import write_sqlite_audit_log
from web.app.services.internal_transfers import (
    ensure_internal_transfer_tables,
    mark_bulk_adjustments,
    mark_employee_adjustments,
)

try:
    from web.app.config import config
except Exception:
    config = None


router = APIRouter(tags=["admin_payout_summary"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def db_path() -> str:
    if config is not None:
        url = getattr(config, "DATABASE_URL", "")
        if isinstance(url, str) and url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "", 1)
    return str(Path.cwd() / "web_dashboard.db")


def summary_db_path() -> str:
    return db_path()


def ensure_worker_tip_table() -> None:
    conn = sqlite3.connect(db_path())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                wallet_transaction_id INTEGER,
                confirmation_message_id TEXT,
                confirmed_by_discord_id TEXT,
                confirmed_by_display_name TEXT,
                paid_at TEXT,
                payout_paid_at TEXT,
                cancelled_at TEXT,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin(request: Request) -> dict | None:
    user = current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


def require_manager(request: Request) -> dict | None:
    user = current_user(request)
    if not user or not user.get("is_manager"):
        return None
    return user


def normalize_role(role: str | None) -> str:
    return role if role in {"all", "worker", "customer_service"} else "all"


def normalize_payout_status(status: str | None) -> str:
    status = str(status or "unpaid").strip()
    if status in {"paid", "已發放", "已支付"}:
        return "paid"
    if status in {"all", "全部", "全部狀態"}:
        return "all"
    return "unpaid"


def payout_order_date_expr(alias: str = "w") -> str:
    return (
        f"COALESCE("
        f"NULLIF({alias}.closed_at, ''), "
        f"NULLIF({alias}.updated_at, ''), "
        f"NULLIF({alias}.created_at, '')"
        f")"
    )


def month_filter_sql(month: str | None, alias: str) -> tuple[str, list[str]]:
    month = str(month or "").strip()
    if not month:
        return "", []
    return f" AND substr({payout_order_date_expr(alias)}, 1, 7) = ? ", [month]


def add_person(
    people: dict[str, dict],
    *,
    discord_id,
    display_name,
    role,
    amount,
    order_no,
    category,
    item,
    payout_status,
    customer_name=None,
    closed_at=None,
    item_role_label=None,
) -> None:
    discord_id = str(discord_id or "").strip()
    if not discord_id:
        return

    payout_status = "paid" if str(payout_status or "") == "paid" else "unpaid"
    if discord_id not in people:
        people[discord_id] = {
            "discord_id": discord_id,
            "display_name": display_name or discord_id,
            "roles": set(),
            "role_label": "人員",
            "unpaid_total": 0,
            "unpaid_count": 0,
            "paid_total": 0,
            "paid_count": 0,
            "items": [],
        }

    person = people[discord_id]
    if display_name and person["display_name"] == discord_id:
        person["display_name"] = display_name

    person["roles"].add(role)
    amount = int(amount or 0)
    if payout_status == "paid":
        person["paid_total"] += amount
        person["paid_count"] += 1
    else:
        person["unpaid_total"] += amount
        person["unpaid_count"] += 1

    closed_text = str(closed_at or "").strip()
    person["items"].append(
        {
            "order_no": order_no,
            "category": category or "",
            "item": item or "",
            "customer_name": str(customer_name or "").strip() or "未紀錄",
            "closed_date": closed_text[:10] if closed_text else "未紀錄",
            "role": item_role_label or ("護航 / 陪玩" if role == "worker" else "客服"),
            "amount": amount,
            "payout_status": payout_status,
            "status_label": "已支付" if payout_status == "paid" else "未支付",
        }
    )


def finalize_people(
    people: dict[str, dict],
    q: str | None,
    status: str | None = "unpaid",
) -> list[dict]:
    keyword = str(q or "").strip().lower()
    status = normalize_payout_status(status)
    rows: list[dict] = []

    for person in people.values():
        roles = person.pop("roles", set())
        if roles == {"worker"}:
            person["role_label"] = "護航 / 陪玩"
            person["role"] = "worker"
        elif roles == {"customer_service"}:
            person["role_label"] = "客服"
            person["role"] = "customer_service"
        elif roles:
            person["role_label"] = "混合"
            person["role"] = "all"
        else:
            person["role"] = "all"

        if status == "paid":
            if int(person.get("paid_total") or 0) <= 0:
                continue
            person["display_total"] = person["paid_total"]
            person["display_count"] = person["paid_count"]
            person["display_status"] = "已支付"
        elif status == "all":
            total = int(person.get("paid_total") or 0) + int(person.get("unpaid_total") or 0)
            count = int(person.get("paid_count") or 0) + int(person.get("unpaid_count") or 0)
            if total <= 0 and count <= 0:
                continue
            person["display_total"] = total
            person["display_count"] = count
            person["display_status"] = "全部"
        else:
            if int(person.get("unpaid_total") or 0) <= 0:
                continue
            person["display_total"] = person["unpaid_total"]
            person["display_count"] = person["unpaid_count"]
            person["display_status"] = "未支付"

        person["items"].sort(
            key=lambda item: (str(item.get("closed_date") or ""), str(item.get("order_no") or "")),
            reverse=True,
        )

        if keyword:
            haystack = f'{person["display_name"]} {person["discord_id"]}'.lower()
            if keyword not in haystack:
                continue
        rows.append(person)

    return sorted(
        rows,
        key=lambda row: (-int(row.get("display_total") or 0), str(row.get("display_name") or "")),
    )


def _adjustment_role_sql(role: str) -> str:
    role = normalize_role(role)
    if role == "worker":
        return (
            " AND (COALESCE(m.is_worker, 0) = 1 OR COALESCE(m.is_companion, 0) = 1) "
        )
    if role == "customer_service":
        return " AND COALESCE(m.is_customer_service, 0) = 1 "
    return ""


def fetch_rows(
    month: str | None,
    role: str | None,
    q: str | None,
    status: str | None = "unpaid",
):
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    role = normalize_role(role)
    status = normalize_payout_status(status)
    people: dict[str, dict] = {}

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row

    payout_status_sql = ""
    payout_status_params: list[str] = []
    if status in {"unpaid", "paid"}:
        payout_status_sql = " AND p.payout_status = ? "
        payout_status_params.append(status)

    try:
        if role in {"all", "worker"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(
                f"""
                SELECT
                    p.worker_discord_id AS discord_id,
                    p.worker_display_name AS display_name,
                    p.final_payout AS amount,
                    p.payout_status AS payout_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND COALESCE(p.final_payout, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="worker",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

            tip_rows = conn.execute(
                f"""
                SELECT
                    p.worker_discord_id AS discord_id,
                    p.worker_display_name AS display_name,
                    p.amount AS amount,
                    p.payout_status AS payout_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM worker_tips p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payment_status = 'paid'
                  AND COALESCE(p.amount, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in tip_rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="worker",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                    item_role_label="🍗 雞腿",
                )

        if role in {"all", "customer_service"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(
                f"""
                SELECT
                    p.customer_service_discord_id AS discord_id,
                    p.customer_service_display_name AS display_name,
                    p.payout_amount AS amount,
                    p.payout_status AS payout_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM customer_service_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND COALESCE(p.customer_service_discord_id, '') <> ''
                  AND COALESCE(p.customer_service_discord_id, '') <> 'demo_customer_service'
                  AND COALESCE(p.customer_service_display_name, '') <> '測試客服'
                  AND COALESCE(p.payout_amount, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="customer_service",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

        adjustment_status_sql = ""
        adjustment_status_params: list[str] = []
        if status in {"unpaid", "paid"}:
            adjustment_status_sql = " AND a.payout_status = ? "
            adjustment_status_params.append(status)

        adjustment_month_sql = ""
        adjustment_month_params: list[str] = []
        month_value = str(month or "").strip()
        if month_value:
            adjustment_month_sql = " AND substr(a.effective_at, 1, 7) = ? "
            adjustment_month_params.append(month_value)

        adjustment_rows = conn.execute(
            f"""
            SELECT
                a.transfer_id,
                a.employee_discord_id AS discord_id,
                COALESCE(NULLIF(a.employee_display_name, ''), a.employee_discord_id) AS display_name,
                a.counterparty_display_name,
                a.direction,
                a.amount,
                a.reason,
                a.payout_status,
                a.effective_at,
                COALESCE(m.is_customer_service, 0) AS is_customer_service,
                COALESCE(m.is_worker, 0) AS is_worker,
                COALESCE(m.is_companion, 0) AS is_companion
            FROM employee_payroll_adjustments a
            LEFT JOIN web_staff_members m
              ON CAST(m.discord_id AS TEXT) = CAST(a.employee_discord_id AS TEXT)
            WHERE 1 = 1
              {adjustment_status_sql}
              {adjustment_month_sql}
              {_adjustment_role_sql(role)}
            ORDER BY a.effective_at DESC, a.id DESC
            """,
            [*adjustment_status_params, *adjustment_month_params],
        ).fetchall()

        for row in adjustment_rows:
            is_cs = bool(int(row["is_customer_service"] or 0))
            is_worker = bool(int(row["is_worker"] or 0) or int(row["is_companion"] or 0))
            role_key = "customer_service" if is_cs and not is_worker else "worker"
            counterparty = str(row["counterparty_display_name"] or "內部員工")
            direction = str(row["direction"] or "")
            label = (
                f"轉入｜來自 {counterparty}"
                if direction == "incoming"
                else f"轉出｜給 {counterparty}"
            )
            reason = str(row["reason"] or "").strip()
            if reason:
                label += f"｜{reason}"

            add_person(
                people,
                discord_id=row["discord_id"],
                display_name=row["display_name"],
                role=role_key,
                amount=row["amount"],
                payout_status=row["payout_status"],
                customer_name=counterparty,
                closed_at=row["effective_at"],
                order_no=f"內部轉帳 #{int(row['transfer_id'])}",
                category="內部轉帳",
                item=label,
                item_role_label="內部轉帳",
            )
            if is_cs and is_worker:
                people[str(row["discord_id"])]["roles"].add("customer_service")

    finally:
        conn.close()

    rows = finalize_people(people, q, status)
    totals = {
        "person_count": len(rows),
        "unpaid_total": sum(int(row.get("unpaid_total") or 0) for row in rows),
        "unpaid_count": sum(int(row.get("unpaid_count") or 0) for row in rows),
        "paid_total": sum(int(row.get("paid_total") or 0) for row in rows),
        "paid_count": sum(int(row.get("paid_count") or 0) for row in rows),
        "display_total": sum(int(row.get("display_total") or 0) for row in rows),
        "display_count": sum(int(row.get("display_count") or 0) for row in rows),
    }
    return rows, totals


def _audit_payout_state(
    month: str | None,
    role: str | None,
    *,
    person_id: str | None = None,
) -> dict:
    rows, totals = fetch_rows(month, role, "", "all")
    person_value = str(person_id or "").strip()
    if person_value:
        rows = [row for row in rows if str(row.get("discord_id") or "") == person_value]
        totals = {
            "person_count": len(rows),
            "unpaid_total": sum(int(row.get("unpaid_total") or 0) for row in rows),
            "unpaid_count": sum(int(row.get("unpaid_count") or 0) for row in rows),
            "paid_total": sum(int(row.get("paid_total") or 0) for row in rows),
            "paid_count": sum(int(row.get("paid_count") or 0) for row in rows),
        }
    return {
        "month": str(month or "").strip() or "全部月份",
        "role": str(role or "all").strip(),
        "person_id": person_value or None,
        "totals": totals,
        "people": [
            {
                "discord_id": row.get("discord_id"),
                "display_name": row.get("display_name"),
                "unpaid_total": int(row.get("unpaid_total") or 0),
                "paid_total": int(row.get("paid_total") or 0),
            }
            for row in rows
        ],
    }


def get_summary_month_options() -> list[dict]:
    ensure_internal_transfer_tables(db_path())
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT month_value
            FROM (
                SELECT substr(
                    COALESCE(NULLIF(closed_at, ''), NULLIF(updated_at, ''), NULLIF(created_at, '')),
                    1,
                    7
                ) AS month_value
                FROM web_orders
                WHERE status = 'closed'
                UNION ALL
                SELECT substr(effective_at, 1, 7) AS month_value
                FROM employee_payroll_adjustments
            )
            WHERE month_value GLOB '????-??'
            ORDER BY month_value DESC
            """
        ).fetchall()
    finally:
        conn.close()

    options = []
    for row in rows:
        value = str(row["month_value"] or "").strip()
        if not value:
            continue
        try:
            year, month_number = value.split("-", 1)
            label = f"{int(year)}年{int(month_number)}月"
        except Exception:
            label = value
        options.append({"value": value, "label": label})
    return options


def normalize_summary_month(month: str | None) -> str:
    return str(month or "").strip()


def build_summary_bulk_redirect(month: str | None, status: str | None, role: str | None) -> str:
    from urllib.parse import urlencode

    query = {}
    if month:
        query["month"] = month
    if role:
        query["role"] = role
    return "/admin/payouts/summary?" + urlencode(query)


def update_summary_payout_status(
    month: str | None,
    role: str | None,
    target_status: str,
) -> None:
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    month = normalize_summary_month(month)
    role = str(role or "all").strip()
    target_status = "paid" if target_status == "paid" else "unpaid"
    paid_at_sql = "datetime('now', '+8 hours')" if target_status == "paid" else "NULL"

    conn = sqlite3.connect(summary_db_path())
    try:
        order_filter = "w.status = 'closed'"
        params: list[str] = []
        if month:
            order_filter += (
                " AND substr(COALESCE(NULLIF(w.closed_at, ''), "
                "NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            )
            params.append(month)

        if role in {"all", "", "worker", "護航 / 陪玩"}:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                )
                """,
                [target_status, *params],
            )
            conn.execute(
                f"""
                UPDATE worker_tips
                SET payout_status = ?,
                    payout_paid_at = {paid_at_sql},
                    updated_at = datetime('now', '+8 hours')
                WHERE payment_status = 'paid'
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                [target_status, *params],
            )

        if role in {"all", "", "customer_service", "客服"}:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                )
                  AND COALESCE(customer_service_discord_id, '') <> ''
                  AND COALESCE(customer_service_discord_id, '') <> 'demo_customer_service'
                  AND COALESCE(customer_service_display_name, '') <> '測試客服'
                """,
                [target_status, *params],
            )
        conn.commit()
    finally:
        conn.close()

    mark_bulk_adjustments(
        target_status=target_status,
        month=month,
        role=role,
    )


def update_summary_person_payout_status(
    month: str,
    person_role: str,
    person_id: str,
    target_status: str,
):
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    person_id = str(person_id or "").strip()
    if not person_id:
        return

    target_status = "paid" if str(target_status or "").strip() == "paid" else "unpaid"
    paid_at_sql = "datetime('now', '+8 hours')" if target_status == "paid" else "NULL"
    role_text = str(person_role or "").strip().lower()

    update_worker = role_text in {
        "worker", "護航 / 陪玩", "worker_payout", "護航 / 陪玩分潤",
        "mixed", "mix", "both", "hybrid", "混合", "混合身分",
        "客服 / 護航", "護航 / 客服", "總控 / 客服 / 護航",
    }
    update_customer_service = role_text in {
        "customer_service", "customer-service", "cs", "客服", "魔丸♫客服分潤",
        "mixed", "mix", "both", "hybrid", "混合", "混合身分",
        "客服 / 護航", "護航 / 客服", "總控 / 客服 / 護航",
    }
    if not update_worker and not update_customer_service:
        update_worker = True
        update_customer_service = True

    conn = sqlite3.connect(db_path())
    try:
        order_filter = "w.status = 'closed'"
        params_worker: list[str] = [target_status, person_id]
        params_cs: list[str] = [target_status, person_id]
        if month:
            order_filter += (
                " AND substr(COALESCE(NULLIF(w.closed_at, ''), "
                "NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            )
            params_worker.append(month)
            params_cs.append(month)

        if update_worker:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE worker_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                params_worker,
            )
            conn.execute(
                f"""
                UPDATE worker_tips
                SET payout_status = ?,
                    payout_paid_at = {paid_at_sql},
                    updated_at = datetime('now', '+8 hours')
                WHERE payment_status = 'paid'
                  AND worker_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                params_worker,
            )

        if update_customer_service:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE customer_service_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                params_cs,
            )
        conn.commit()
    finally:
        conn.close()

    mark_employee_adjustments(
        employee_discord_id=person_id,
        target_status=target_status,
        month=month,
    )


def build_combined_summary_rows(
    unpaid_rows: list[dict],
    paid_rows: list[dict],
) -> list[dict]:
    combined: dict[tuple[str, str], dict] = {}

    def as_number(value) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0

    def as_int(value) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def get_value(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    def ensure_row(row) -> dict:
        role = str(get_value(row, "role", "") or "")
        discord_id = str(get_value(row, "discord_id", "") or "")
        key = (role, discord_id)
        if key not in combined:
            combined[key] = {
                "role": role,
                "role_label": get_value(row, "role_label", role or "人員"),
                "discord_id": discord_id,
                "display_name": get_value(row, "display_name", discord_id or "未知人員"),
                "unpaid_total": 0,
                "paid_total": 0,
                "unpaid_count": 0,
                "paid_count": 0,
                "items": [],
            }
        return combined[key]

    for row in unpaid_rows or []:
        target = ensure_row(row)
        target["unpaid_total"] += as_number(
            get_value(row, "display_total", get_value(row, "unpaid_total", 0))
        )
        target["unpaid_count"] += as_int(get_value(row, "unpaid_count", 0))
        target["items"].extend(list(get_value(row, "items", []) or []))

    for row in paid_rows or []:
        target = ensure_row(row)
        target["paid_total"] += as_number(get_value(row, "paid_total", 0))
        target["paid_count"] += as_int(get_value(row, "paid_count", 0))
        target["items"].extend(list(get_value(row, "items", []) or []))

    rows = list(combined.values())
    for row in rows:
        row["total_count"] = int(row["unpaid_count"] or 0) + int(row["paid_count"] or 0)
        if row["unpaid_count"] and row["paid_count"]:
            row["summary_status"] = "部分待審"
            row["summary_status_class"] = "partial"
        elif row["unpaid_count"]:
            row["summary_status"] = "待發放"
            row["summary_status_class"] = "unpaid"
        else:
            row["summary_status"] = "正常"
            row["summary_status_class"] = "paid"

    rows.sort(
        key=lambda row: (
            int(row.get("unpaid_count") or 0) <= 0,
            -float(row.get("unpaid_total") or 0),
            str(row.get("display_name") or ""),
        )
    )
    return rows


def attach_staff_avatars_to_summary_rows(rows: list[dict]) -> list[dict]:
    discord_ids = [
        str(row.get("discord_id") or "").strip()
        for row in rows or []
        if str(row.get("discord_id") or "").strip()
    ]
    if not discord_ids:
        return rows

    conn = sqlite3.connect(summary_db_path())
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in discord_ids)
        avatar_rows = conn.execute(
            f"SELECT discord_id, avatar FROM web_staff_members WHERE discord_id IN ({placeholders})",
            discord_ids,
        ).fetchall()
        avatar_map = {
            str(item["discord_id"]): str(item["avatar"] or "")
            for item in avatar_rows
        }
    finally:
        conn.close()

    for row in rows:
        discord_id = str(row.get("discord_id") or "").strip()
        avatar = avatar_map.get(discord_id, "")
        row["avatar"] = avatar
        if avatar:
            ext = "gif" if avatar.startswith("a_") else "png"
            row["avatar_url"] = (
                f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.{ext}?size=128"
            )
        else:
            row["avatar_url"] = ""
    return rows


@router.get("/admin/payouts/summary")
async def admin_payout_summary(
    request: Request,
    month: str | None = "",
    role: str | None = "all",
    q: str | None = "",
):
    user = require_admin(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
                "user": current_user(request),
            },
            status_code=403,
        )

    role = normalize_role(role)
    status = "unpaid"
    rows, totals = fetch_rows(month, role, q, status)
    unpaid_rows, unpaid_totals = fetch_rows(month, role, q, "unpaid")
    paid_rows, paid_totals = fetch_rows(month, role, q, "paid")
    summary_rows = build_combined_summary_rows(unpaid_rows, paid_rows)

    return templates.TemplateResponse(
        request=request,
        name="admin_payout_summary.html",
        context={
            "title": "人員總表",
            "user": user,
            "rows": rows,
            "unpaid_rows": unpaid_rows,
            "paid_rows": paid_rows,
            "unpaid_totals": unpaid_totals,
            "paid_totals": paid_totals,
            "totals": totals,
            "summary_rows": summary_rows,
            "month": month or "",
            "month_options": get_summary_month_options(),
            "role": role,
            "status": status,
            "q": q or "",
        },
    )


@router.get("/admin/payouts/summary.csv")
async def admin_payout_summary_csv(
    request: Request,
    month: str | None = "",
    role: str | None = "all",
    q: str | None = "",
):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    rows, totals = fetch_rows(month, role, q, "unpaid")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["身份", "名稱", "Discord ID", "未支付", "筆數"])
    for row in rows:
        writer.writerow(
            [
                row["role_label"],
                row["display_name"],
                row["discord_id"],
                row["unpaid_total"],
                row["unpaid_count"],
            ]
        )
    writer.writerow(["合計", "", "", totals["unpaid_total"], totals["unpaid_count"]])
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="payout_unpaid_summary.csv"'},
    )


@router.get("/admin/month-options")
async def admin_month_options(request: Request):
    user = require_admin(request)
    if not user:
        return JSONResponse({"ok": False, "months": []}, status_code=403)
    return {"ok": True, "months": get_summary_month_options()}


@router.post("/admin/payouts/summary/mark-paid")
async def mark_summary_payouts_paid(request: Request):
    user = require_manager(request)
    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    form = await request.form()
    month = str(form.get("month") or "").strip()
    role = str(form.get("role") or "all").strip()
    before = _audit_payout_state(month, role)
    update_summary_payout_status(month, role, "paid")
    after = _audit_payout_state(month, role)
    write_sqlite_audit_log(
        admin_discord_id=str(user.get("id") or ""),
        action="bulk_set_payout_status",
        target_type="payout_batch",
        target_id=f"{month or 'all'}:{role or 'all'}",
        before=before,
        after={**after, "target_status": "paid"},
        reason="批次標記薪資已發放",
        db_file=db_path(),
    )
    return RedirectResponse(
        url=build_summary_bulk_redirect(month, "paid", role),
        status_code=303,
    )


@router.post("/admin/payouts/summary/mark-unpaid")
async def mark_summary_payouts_unpaid(request: Request):
    user = require_manager(request)
    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    form = await request.form()
    month = str(form.get("month") or "").strip()
    role = str(form.get("role") or "all").strip()
    before = _audit_payout_state(month, role)
    update_summary_payout_status(month, role, "unpaid")
    after = _audit_payout_state(month, role)
    write_sqlite_audit_log(
        admin_discord_id=str(user.get("id") or ""),
        action="bulk_set_payout_status",
        target_type="payout_batch",
        target_id=f"{month or 'all'}:{role or 'all'}",
        before=before,
        after={**after, "target_status": "unpaid"},
        reason="批次標記薪資未發放",
        db_file=db_path(),
    )
    return RedirectResponse(
        url=build_summary_bulk_redirect(month, "unpaid", role),
        status_code=303,
    )


@router.post("/admin/payouts/summary/person-status")
async def update_summary_person_status(request: Request):
    user = require_manager(request)
    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    form = await request.form()
    month = str(form.get("month") or "").strip()
    current_role = str(form.get("current_role") or "all").strip()
    person_role = str(form.get("person_role") or "").strip()
    person_id = str(form.get("person_id") or "").strip()
    target_status = str(form.get("target_status") or "unpaid").strip()

    before = _audit_payout_state(month, person_role, person_id=person_id)
    update_summary_person_payout_status(month, person_role, person_id, target_status)
    after = _audit_payout_state(month, person_role, person_id=person_id)
    write_sqlite_audit_log(
        admin_discord_id=str(user.get("id") or ""),
        action="set_person_payout_status",
        target_type="payout_person",
        target_id=person_id,
        before=before,
        after={
            **after,
            "target_status": target_status,
            "person_role": person_role,
        },
        reason="更新單一人員薪資發放狀態",
        db_file=db_path(),
    )

    from urllib.parse import urlencode

    query = {}
    if month:
        query["month"] = month
    if current_role:
        query["role"] = current_role
    url = "/admin/payouts/summary"
    if query:
        url += "?" + urlencode(query)
    return RedirectResponse(url=url, status_code=303)


def _shift_month_start(value: datetime, months: int) -> datetime:
    total_months = value.year * 12 + (value.month - 1) + months
    year, month_zero = divmod(total_months, 12)
    return value.replace(
        year=year,
        month=month_zero + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _report_period(
    period: str | None,
) -> tuple[str, str | None, str, str | None, str | None, str | None]:
    period = str(period or "quarter").strip().lower()
    now = datetime.utcnow() + timedelta(hours=8)

    if period == "all":
        return "all", None, "全部期間", None, None, None

    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_start = _shift_month_start(start, -1)
        previous_label = "上月同期"
        period_label = "本月"
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_start = start.replace(year=start.year - 1)
        previous_label = "去年同期"
        period_label = "本年度"
    else:
        period = "quarter"
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=quarter_month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        previous_start = _shift_month_start(start, -3)
        previous_label = "上季同期"
        period_label = "本季度"

    current_day_end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elapsed_days = max(1, (current_day_end - start).days)
    previous_end = min(start, previous_start + timedelta(days=elapsed_days))
    return (
        period,
        start.strftime("%Y-%m-%d %H:%M:%S"),
        period_label,
        previous_start.strftime("%Y-%m-%d %H:%M:%S"),
        previous_end.strftime("%Y-%m-%d %H:%M:%S"),
        previous_label,
    )


def _report_change(current: int | float, previous: int | float) -> dict:
    current_value = float(current or 0)
    previous_value = float(previous or 0)
    delta = current_value - previous_value
    rate = round(delta * 100 / previous_value, 1) if previous_value else None
    return {
        "previous": round(previous_value, 1),
        "delta": round(delta, 1),
        "rate": rate,
    }


def build_operations_report(period: str | None) -> dict:
    (
        period,
        start_at,
        period_label,
        previous_start_at,
        previous_end_at,
        previous_label,
    ) = _report_period(period)

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    closed_expr = (
        "COALESCE("
        "NULLIF(w.closed_at,''), "
        "datetime(NULLIF(w.updated_at,''), '+8 hours'), "
        "datetime(w.created_at, '+8 hours')"
        ")"
    )

    def order_window(
        start_value: str | None,
        end_value: str | None = None,
    ) -> tuple[list[sqlite3.Row], str, list[str]]:
        where = "WHERE w.status = 'closed'"
        params: list[str] = []
        if start_value:
            where += f" AND {closed_expr} >= ?"
            params.append(start_value)
        if end_value:
            where += f" AND {closed_expr} < ?"
            params.append(end_value)
        rows = conn.execute(
            f"""
            SELECT
                w.id,
                w.bot_order_no,
                w.category,
                w.item,
                w.customer_discord_id,
                w.customer_display_name,
                COALESCE(w.customer_pay_amount, w.amount, 0) AS revenue,
                COALESCE(NULLIF(TRIM(w.payment_method), ''), '未紀錄') AS payment_method,
                COALESCE(w.manual_discount_amount, 0) AS percent_discount,
                COALESCE(w.cash_coupon_amount, 0) AS fixed_discount,
                COALESCE(w.store_absorbed_amount, 0) AS point_discount,
                {closed_expr} AS closed_at,
                COALESCE((
                    SELECT SUM(p.final_payout)
                    FROM worker_payouts p
                    WHERE p.order_id = w.id
                ), 0) AS worker_cost,
                COALESCE((
                    SELECT SUM(p.payout_amount)
                    FROM customer_service_payouts p
                    WHERE p.order_id = w.id
                ), 0) AS service_cost
            FROM web_orders w
            {where}
            ORDER BY closed_at ASC
            """,
            params,
        ).fetchall()
        return rows, where, params

    def summarize(rows: list[sqlite3.Row]) -> dict:
        revenue = sum(int(row["revenue"] or 0) for row in rows)
        worker_cost = sum(int(row["worker_cost"] or 0) for row in rows)
        service_cost = sum(int(row["service_cost"] or 0) for row in rows)
        payroll = worker_cost + service_cost
        retained = revenue - payroll
        order_count = len(rows)
        avg_order = round(revenue / order_count) if order_count else 0
        percent_discount = sum(max(0, int(row["percent_discount"] or 0)) for row in rows)
        fixed_discount = sum(max(0, int(row["fixed_discount"] or 0)) for row in rows)
        point_discount = sum(max(0, int(row["point_discount"] or 0)) for row in rows)
        discount_total = percent_discount + fixed_discount + point_discount
        retained_rate = round(retained * 100 / revenue, 1) if revenue else 0.0
        payroll_rate = round(payroll * 100 / revenue, 1) if revenue else 0.0

        customers: dict[str, int] = {}
        for row in rows:
            customer_id = str(row["customer_discord_id"] or "").strip()
            if customer_id:
                customers[customer_id] = customers.get(customer_id, 0) + 1
        repeat_customers = sum(1 for count in customers.values() if count >= 2)
        repeat_rate = round(repeat_customers * 100 / len(customers), 1) if customers else 0.0
        return {
            "revenue": revenue,
            "worker_cost": worker_cost,
            "service_cost": service_cost,
            "payroll": payroll,
            "retained": retained,
            "retained_rate": retained_rate,
            "payroll_rate": payroll_rate,
            "order_count": order_count,
            "avg_order": avg_order,
            "customer_count": len(customers),
            "repeat_customers": repeat_customers,
            "repeat_rate": repeat_rate,
            "percent_discount": percent_discount,
            "fixed_discount": fixed_discount,
            "point_discount": point_discount,
            "discount_total": discount_total,
        }

    try:
        orders, current_where, current_params = order_window(start_at)
        previous_orders: list[sqlite3.Row] = []
        comparison_history_exists = False
        if previous_start_at and previous_end_at:
            previous_orders, _, _ = order_window(previous_start_at, previous_end_at)
            history_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM web_orders w
                WHERE w.status = 'closed' AND {closed_expr} < ?
                """,
                [previous_end_at],
            ).fetchone()
            comparison_history_exists = bool(int(history_row["total"] or 0))

        worker_rows = conn.execute(
            f"""
            SELECT
                p.worker_discord_id,
                COALESCE(NULLIF(p.worker_display_name,''), p.worker_discord_id) AS name,
                SUM(COALESCE(p.final_payout,0)) AS amount,
                COUNT(*) AS jobs
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            {current_where}
            GROUP BY p.worker_discord_id, name
            HAVING amount > 0
            ORDER BY amount DESC
            LIMIT 8
            """,
            current_params,
        ).fetchall()

        customer_history = conn.execute(
            f"""
            SELECT w.id, w.customer_discord_id, {closed_expr} AS closed_at
            FROM web_orders w
            WHERE w.status = 'closed'
              AND TRIM(COALESCE(w.customer_discord_id, '')) <> ''
            ORDER BY closed_at ASC, w.id ASC
            """
        ).fetchall()
        first_closed_order_ids: set[int] = set()
        seen_customer_ids: set[str] = set()
        for history_row in customer_history:
            customer_id = str(history_row["customer_discord_id"] or "").strip()
            if customer_id and customer_id not in seen_customer_ids:
                seen_customer_ids.add(customer_id)
                first_closed_order_ids.add(int(history_row["id"]))

        created_taipei_expr = "datetime(w.created_at, '+8 hours')"

        def cancellation_stats(
            start_value: str | None,
            end_value: str | None = None,
        ) -> dict:
            status_where = "WHERE 1 = 1"
            status_params: list[str] = []
            if start_value:
                status_where += f" AND {created_taipei_expr} >= ?"
                status_params.append(start_value)
            if end_value:
                status_where += f" AND {created_taipei_expr} < ?"
                status_params.append(end_value)
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_orders,
                    SUM(CASE WHEN LOWER(TRIM(COALESCE(w.status, '')))
                        IN ('cancelled', 'canceled') THEN 1 ELSE 0 END) AS cancelled_orders
                FROM web_orders w
                {status_where}
                """,
                status_params,
            ).fetchone()
            total_orders = int(row["total_orders"] or 0)
            cancelled_orders = int(row["cancelled_orders"] or 0)
            return {
                "created_orders": total_orders,
                "cancelled_orders": cancelled_orders,
                "cancellation_rate": (
                    round(cancelled_orders * 100 / total_orders, 1)
                    if total_orders
                    else 0.0
                ),
            }

        cancellation = cancellation_stats(start_at)
    finally:
        conn.close()

    current = summarize(orders)
    previous = summarize(previous_orders)
    daily: dict[str, int] = {}
    services: dict[str, dict] = {}
    payment_methods: dict[str, dict] = {}
    new_customer_revenue = 0
    repeat_customer_revenue = 0
    unidentified_customer_revenue = 0
    new_customer_orders = 0
    repeat_customer_orders = 0
    unidentified_customer_orders = 0

    for row in orders:
        day = str(row["closed_at"] or "")[:10] or "未紀錄"
        daily[day] = daily.get(day, 0) + int(row["revenue"] or 0)
        service = str(row["item"] or row["category"] or "其他")
        bucket = services.setdefault(
            service,
            {
                "label": service,
                "revenue": 0,
                "orders": 0,
                "worker_cost": 0,
                "service_cost": 0,
                "payroll": 0,
                "retained": 0,
                "retained_rate": 0.0,
            },
        )
        row_revenue = int(row["revenue"] or 0)
        row_worker_cost = int(row["worker_cost"] or 0)
        row_service_cost = int(row["service_cost"] or 0)
        customer_id = str(row["customer_discord_id"] or "").strip()
        if not customer_id:
            unidentified_customer_revenue += row_revenue
            unidentified_customer_orders += 1
        elif int(row["id"]) in first_closed_order_ids:
            new_customer_revenue += row_revenue
            new_customer_orders += 1
        else:
            repeat_customer_revenue += row_revenue
            repeat_customer_orders += 1

        payment_method = str(row["payment_method"] or "未紀錄").strip() or "未紀錄"
        payment_bucket = payment_methods.setdefault(
            payment_method,
            {"label": payment_method, "orders": 0, "revenue": 0, "share": 0.0},
        )
        payment_bucket["orders"] += 1
        payment_bucket["revenue"] += row_revenue
        bucket["revenue"] += row_revenue
        bucket["orders"] += 1
        bucket["worker_cost"] += row_worker_cost
        bucket["service_cost"] += row_service_cost
        bucket["payroll"] += row_worker_cost + row_service_cost

    for bucket in services.values():
        bucket["retained"] = bucket["revenue"] - bucket["payroll"]
        bucket["retained_rate"] = (
            round(bucket["retained"] * 100 / bucket["revenue"], 1)
            if bucket["revenue"]
            else 0.0
        )

    service_rows = sorted(
        services.values(),
        key=lambda item: (-item["revenue"], item["label"]),
    )
    tracked_customer_revenue = new_customer_revenue + repeat_customer_revenue
    new_customer_revenue_share = (
        round(new_customer_revenue * 100 / tracked_customer_revenue, 1)
        if tracked_customer_revenue
        else 0.0
    )
    repeat_customer_revenue_share = (
        round(repeat_customer_revenue * 100 / tracked_customer_revenue, 1)
        if tracked_customer_revenue
        else 0.0
    )

    payment_rows = sorted(
        payment_methods.values(),
        key=lambda item: (-item["revenue"], item["label"]),
    )
    for payment_row in payment_rows:
        payment_row["share"] = (
            round(payment_row["revenue"] * 100 / current["revenue"], 1)
            if current["revenue"]
            else 0.0
        )

    comparison = {}
    if previous_start_at and previous_end_at:
        comparison = {
            "revenue": _report_change(current["revenue"], previous["revenue"]),
            "payroll": _report_change(current["payroll"], previous["payroll"]),
            "retained": _report_change(current["retained"], previous["retained"]),
            "avg_order": _report_change(current["avg_order"], previous["avg_order"]),
            "order_count": _report_change(current["order_count"], previous["order_count"]),
            "customer_count": _report_change(current["customer_count"], previous["customer_count"]),
        }

    return {
        "period": period,
        "period_label": period_label,
        "previous_label": previous_label,
        "comparison": comparison,
        "comparison_history_exists": comparison_history_exists,
        **current,
        "daily_labels": list(daily.keys()),
        "daily_values": list(daily.values()),
        "service_rows": service_rows[:10],
        "service_labels": [row["label"] for row in service_rows[:8]],
        "service_values": [row["revenue"] for row in service_rows[:8]],
        "worker_rows": [dict(row) for row in worker_rows],
        "new_customer_revenue": new_customer_revenue,
        "new_customer_orders": new_customer_orders,
        "new_customer_revenue_share": new_customer_revenue_share,
        "repeat_customer_revenue": repeat_customer_revenue,
        "repeat_customer_orders": repeat_customer_orders,
        "repeat_customer_revenue_share": repeat_customer_revenue_share,
        "unidentified_customer_revenue": unidentified_customer_revenue,
        "unidentified_customer_orders": unidentified_customer_orders,
        "payment_rows": payment_rows,
        **cancellation,
    }


@router.get("/admin/payouts/report")
async def admin_operations_report(
    request: Request,
    period: str | None = "quarter",
):
    user = require_admin(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
                "user": current_user(request),
            },
            status_code=403,
        )

    report = build_operations_report(period)
    return templates.TemplateResponse(
        request=request,
        name="admin_operations_report.html",
        context={
            "title": "營運財務報表",
            "user": user,
            "report": report,
        },
    )
