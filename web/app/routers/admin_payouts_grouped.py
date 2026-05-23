from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from web.app.config import config

router = APIRouter(tags=["admin_payouts_grouped"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def redirect_to_grouped(**params) -> RedirectResponse:
    query = {k: v for k, v in params.items() if v not in (None, "")}
    url = "/admin/payouts/grouped"

    if query:
        url += f"?{urlencode(query)}"

    return RedirectResponse(url=url, status_code=303)


def sqlite_path_from_database_url() -> str:
    database_url = config.DATABASE_URL

    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)

    raise RuntimeError("Grouped payout page only supports sqlite DATABASE_URL for now.")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path_from_database_url())
    conn.row_factory = sqlite3.Row
    return conn


def normalize_filter(value: str | None, allowed: set[str], default: str) -> str:
    value = (value or default).strip()
    return value if value in allowed else default


def month_condition(alias: str, month: str | None) -> tuple[str, list[str]]:
    month = (month or "").strip()

    if not month:
        return "", []

    return f" AND strftime('%Y-%m', {alias}.created_at) = ?", [month]


def status_condition(alias: str, status: str) -> tuple[str, list[str]]:
    if status == "all":
        return "", []

    return f" AND {alias}.payout_status = ?", [status]


def fetch_rows(conn: sqlite3.Connection, *, month: str, status: str, role: str) -> list[dict]:
    rows: list[dict] = []

    if role in {"all", "worker"}:
        month_sql, month_params = month_condition("p", month)
        status_sql, status_params = status_condition("p", status)

        worker_sql = f"""
            SELECT
                'worker' AS payout_role,
                p.id AS payout_id,
                p.order_id AS order_id,
                p.worker_discord_id AS person_id,
                COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS person_name,
                COALESCE(o.bot_order_no, 'WEB-' || o.id) AS order_no,
                COALESCE(o.category, '') AS category,
                COALESCE(o.item, '') AS item,
                p.base_payout AS base_amount,
                p.named_bonus_amount AS bonus_amount,
                p.final_payout AS final_amount,
                p.payout_status AS payout_status,
                p.paid_at AS paid_at,
                p.created_at AS created_at
            FROM worker_payouts p
            LEFT JOIN web_orders o ON o.id = p.order_id
            WHERE 1 = 1
            {month_sql}
            {status_sql}
            ORDER BY person_name ASC, p.created_at DESC, p.id DESC
        """

        rows.extend(dict(row) for row in conn.execute(worker_sql, [*month_params, *status_params]).fetchall())

    if role in {"all", "customer_service"}:
        month_sql, month_params = month_condition("p", month)
        status_sql, status_params = status_condition("p", status)

        service_sql = f"""
            SELECT
                'customer_service' AS payout_role,
                p.id AS payout_id,
                p.order_id AS order_id,
                p.customer_service_discord_id AS person_id,
                COALESCE(NULLIF(p.customer_service_display_name, ''), p.customer_service_discord_id) AS person_name,
                COALESCE(o.bot_order_no, 'WEB-' || o.id) AS order_no,
                COALESCE(o.category, '') AS category,
                COALESCE(o.item, '') AS item,
                p.payout_amount AS base_amount,
                0 AS bonus_amount,
                p.payout_amount AS final_amount,
                p.payout_status AS payout_status,
                p.paid_at AS paid_at,
                p.created_at AS created_at
            FROM customer_service_payouts p
            LEFT JOIN web_orders o ON o.id = p.order_id
            WHERE 1 = 1
            {month_sql}
            {status_sql}
            ORDER BY person_name ASC, p.created_at DESC, p.id DESC
        """

        rows.extend(dict(row) for row in conn.execute(service_sql, [*month_params, *status_params]).fetchall())

    return rows


def group_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}

    for row in rows:
        key = (str(row["payout_role"]), str(row["person_id"] or ""))

        if key not in grouped:
            grouped[key] = {
                "payout_role": row["payout_role"],
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "unpaid_total": 0,
                "paid_total": 0,
                "all_total": 0,
                "count": 0,
                "rows": [],
            }

        group = grouped[key]
        amount = int(row["final_amount"] or 0)
        group["all_total"] += amount
        group["count"] += 1
        group["rows"].append(row)

        if row["payout_status"] == "paid":
            group["paid_total"] += amount
        else:
            group["unpaid_total"] += amount

    return sorted(
        grouped.values(),
        key=lambda item: (item["payout_role"], str(item["person_name"] or "")),
    )


def build_summary(groups: list[dict]) -> dict:
    return {
        "people_count": len(groups),
        "row_count": sum(group["count"] for group in groups),
        "unpaid_total": sum(group["unpaid_total"] for group in groups),
        "paid_total": sum(group["paid_total"] for group in groups),
        "all_total": sum(group["all_total"] for group in groups),
    }


@router.get("/admin/payouts/grouped")
async def grouped_payouts(
    request: Request,
    month: str | None = None,
    status: str = "unpaid",
    role: str = "all",
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": get_current_user(request),
            },
            status_code=403,
        )

    status = normalize_filter(status, {"all", "unpaid", "paid"}, "unpaid")
    role = normalize_filter(role, {"all", "worker", "customer_service"}, "all")
    month = (month or "").strip()

    conn = connect_db()

    try:
        rows = fetch_rows(conn, month=month, status=status, role=role)
        groups = group_rows(rows)
        summary = build_summary(groups)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_payouts_grouped.html",
        context={
            "title": "月結分潤",
            "user": user,
            "groups": groups,
            "summary": summary,
            "month": month,
            "status": status,
            "role": role,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/payouts/grouped/status")
async def update_group_status(
    request: Request,
    payout_role: str = Form(...),
    person_id: str = Form(...),
    new_status: str = Form(...),
    month: str | None = Form(default=""),
    status: str | None = Form(default="unpaid"),
    role: str | None = Form(default="all"),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_grouped(error="你沒有總控後台權限。")

    payout_role = normalize_filter(payout_role, {"worker", "customer_service"}, "worker")
    new_status = normalize_filter(new_status, {"unpaid", "paid"}, "unpaid")
    status = normalize_filter(status, {"all", "unpaid", "paid"}, "unpaid")
    role = normalize_filter(role, {"all", "worker", "customer_service"}, "all")
    month = (month or "").strip()

    table = "worker_payouts" if payout_role == "worker" else "customer_service_payouts"
    person_col = "worker_discord_id" if payout_role == "worker" else "customer_service_discord_id"

    conditions = [f"{person_col} = ?"]
    params: list[str] = [person_id]

    if month:
        conditions.append("strftime('%Y-%m', created_at) = ?")
        params.append(month)

    if status != "all":
        conditions.append("payout_status = ?")
        params.append(status)

    set_paid_at = "CURRENT_TIMESTAMP" if new_status == "paid" else "NULL"
    sql = f"""
        UPDATE {table}
        SET payout_status = ?, paid_at = {set_paid_at}
        WHERE {' AND '.join(conditions)}
    """

    conn = connect_db()

    try:
        cur = conn.execute(sql, [new_status, *params])
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()

    return redirect_to_grouped(
        month=month,
        status=status,
        role=role,
        message=f"已更新 {changed} 筆分潤狀態。",
    )
