from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web.app.config import config


router = APIRouter(tags=["payouts"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def my_payout_db_path() -> str:
    database_url = config.DATABASE_URL

    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)

    raise RuntimeError("My payouts page only supports sqlite DATABASE_URL for now.")


def my_payout_order_date_expr(alias: str = "w") -> str:
    return (
        f"COALESCE("
        f"NULLIF({alias}.closed_at, ''), "
        f"NULLIF({alias}.updated_at, ''), "
        f"NULLIF({alias}.created_at, '')"
        f")"
    )


def normalize_my_payout_status(status: str | None) -> str:
    status = str(status or "all").strip()

    if status in {"paid", "已發放", "已支付"}:
        return "paid"

    if status in {"unpaid", "未發放", "未支付"}:
        return "unpaid"

    return "all"


def get_my_payout_month_options() -> list[dict]:
    conn = sqlite3.connect(my_payout_db_path())
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
            year, month = value.split("-", 1)
            label = f"{int(year)}年{int(month)}月"
        except Exception:
            label = value

        options.append(
            {
                "value": value,
                "label": label,
            }
        )

    return options


def fetch_legacy_rows(discord_id: str) -> tuple[list[dict], list[dict]]:
    """保留舊 summary 需要的 worker_rows / customer_service_rows。"""
    conn = sqlite3.connect(my_payout_db_path())
    conn.row_factory = sqlite3.Row

    try:
        worker_rows = conn.execute(
            """
            SELECT
                p.*,
                COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                w.category,
                w.item,
                w.customer_display_name,
                w.customer_discord_id,
                COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE CAST(p.worker_discord_id AS TEXT) = ?
              AND w.status = 'closed'
              AND COALESCE(p.final_payout, 0) > 0
            ORDER BY closed_at DESC, p.id DESC
            """,
            (discord_id,),
        ).fetchall()

        customer_service_rows = conn.execute(
            """
            SELECT
                p.*,
                COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                w.category,
                w.item,
                w.customer_display_name,
                w.customer_discord_id,
                COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
            FROM customer_service_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE CAST(p.customer_service_discord_id AS TEXT) = ?
              AND w.status = 'closed'
              AND COALESCE(p.customer_service_discord_id, '') <> ''
              AND COALESCE(p.customer_service_discord_id, '') <> 'demo_customer_service'
              AND COALESCE(p.customer_service_display_name, '') <> '測試客服'
              AND COALESCE(p.payout_amount, 0) > 0
            ORDER BY closed_at DESC, p.id DESC
            """,
            (discord_id,),
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in worker_rows], [dict(row) for row in customer_service_rows]


def add_my_payout_item(
    person: dict,
    *,
    order_no,
    closed_at,
    customer_name,
    category,
    item,
    role_label,
    payout_status,
    amount,
):
    payout_status = "paid" if str(payout_status or "") == "paid" else "unpaid"
    amount = int(amount or 0)
    closed_text = str(closed_at or "").strip()
    closed_date = closed_text[:10] if closed_text else "未紀錄"

    if payout_status == "paid":
        person["paid_total"] += amount
        person["paid_count"] += 1
    else:
        person["unpaid_total"] += amount
        person["unpaid_count"] += 1

    person["items"].append(
        {
            "order_no": order_no,
            "closed_date": closed_date,
            "customer_name": customer_name or "未紀錄",
            "category": category or "",
            "item": item or "",
            "role": role_label,
            "payout_status": payout_status,
            "amount": amount,
        }
    )


def build_my_payout_rows(discord_id: str, *, month: str = "", status: str = "all") -> tuple[list[dict], list[dict], dict]:
    discord_id = str(discord_id or "").strip()
    month = str(month or "").strip()
    status = normalize_my_payout_status(status)

    person = {
        "discord_id": discord_id,
        "display_name": "",
        "role_label": "人員",
        "roles": set(),
        "unpaid_total": 0,
        "unpaid_count": 0,
        "paid_total": 0,
        "paid_count": 0,
        "items": [],
    }

    if not discord_id:
        totals = {
            "unpaid_total": 0,
            "unpaid_count": 0,
            "paid_total": 0,
            "paid_count": 0,
            "all_total": 0,
            "all_count": 0,
        }
        return [], [], totals

    payout_status_sql = ""
    payout_status_params = []

    if status in {"paid", "unpaid"}:
        payout_status_sql = " AND p.payout_status = ? "
        payout_status_params.append(status)

    month_sql = ""
    month_params = []

    if month:
        month_sql = f" AND substr({my_payout_order_date_expr('w')}, 1, 7) = ? "
        month_params.append(month)

    conn = sqlite3.connect(my_payout_db_path())
    conn.row_factory = sqlite3.Row

    try:
        worker_rows = conn.execute(
            f"""
            SELECT
                p.worker_discord_id AS discord_id,
                COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                p.final_payout AS amount,
                p.payout_status AS payout_status,
                COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                w.category,
                w.item,
                COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                {my_payout_order_date_expr('w')} AS closed_at
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE w.status = 'closed'
              AND CAST(p.worker_discord_id AS TEXT) = ?
              AND COALESCE(p.final_payout, 0) > 0
              {payout_status_sql}
              {month_sql}
            ORDER BY closed_at DESC, p.id DESC
            """,
            [discord_id, *payout_status_params, *month_params],
        ).fetchall()

        for row in worker_rows:
            if row["display_name"] and not person["display_name"]:
                person["display_name"] = row["display_name"]

            person["roles"].add("worker")
            add_my_payout_item(
                person,
                order_no=row["order_no"],
                closed_at=row["closed_at"],
                customer_name=row["customer_name"],
                category=row["category"],
                item=row["item"],
                role_label="打手",
                payout_status=row["payout_status"],
                amount=row["amount"],
            )

        cs_rows = conn.execute(
            f"""
            SELECT
                p.customer_service_discord_id AS discord_id,
                COALESCE(NULLIF(p.customer_service_display_name, ''), p.customer_service_discord_id) AS display_name,
                p.payout_amount AS amount,
                p.payout_status AS payout_status,
                COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                w.category,
                w.item,
                COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                {my_payout_order_date_expr('w')} AS closed_at
            FROM customer_service_payouts p
            JOIN web_orders w ON w.id = p.order_id
            WHERE w.status = 'closed'
              AND CAST(p.customer_service_discord_id AS TEXT) = ?
              AND COALESCE(p.customer_service_discord_id, '') <> ''
              AND COALESCE(p.customer_service_discord_id, '') <> 'demo_customer_service'
              AND COALESCE(p.customer_service_display_name, '') <> '測試客服'
              AND COALESCE(p.payout_amount, 0) > 0
              {payout_status_sql}
              {month_sql}
            ORDER BY closed_at DESC, p.id DESC
            """,
            [discord_id, *payout_status_params, *month_params],
        ).fetchall()

        for row in cs_rows:
            if row["display_name"] and not person["display_name"]:
                person["display_name"] = row["display_name"]

            person["roles"].add("customer_service")
            add_my_payout_item(
                person,
                order_no=row["order_no"],
                closed_at=row["closed_at"],
                customer_name=row["customer_name"],
                category=row["category"],
                item=row["item"],
                role_label="客服",
                payout_status=row["payout_status"],
                amount=row["amount"],
            )
    finally:
        conn.close()

    if not person["display_name"]:
        person["display_name"] = discord_id

    roles = person.pop("roles", set())

    if roles == {"worker"}:
        person["role_label"] = "打手"
    elif roles == {"customer_service"}:
        person["role_label"] = "客服"
    elif roles:
        person["role_label"] = "總控 / 客服 打手"

    person["items"].sort(key=lambda item: str(item.get("closed_date") or ""), reverse=True)

    unpaid_rows = [person] if person["unpaid_count"] > 0 else []
    paid_rows = [person] if person["paid_count"] > 0 else []

    totals = {
        "unpaid_total": person["unpaid_total"],
        "unpaid_count": person["unpaid_count"],
        "paid_total": person["paid_total"],
        "paid_count": person["paid_count"],
        "all_total": person["unpaid_total"] + person["paid_total"],
        "all_count": person["unpaid_count"] + person["paid_count"],
    }

    return unpaid_rows, paid_rows, totals


@router.get("/my/payouts")
async def my_payouts(request: Request, month: str | None = "", status: str | None = "all"):
    user = get_current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    discord_id = str(user.get("discord_id") or user.get("id") or "").strip()

    summary_unpaid_rows, summary_paid_rows, summary_totals = build_my_payout_rows(
        discord_id,
        month=month or "",
        status=status or "all",
    )

    summary = summary_totals
    worker_rows = []
    customer_service_rows = []

    return templates.TemplateResponse(
        request=request,
        name="my_payouts.html",
        context={
            "title": "我的分潤",
            "user": user,
            "summary": summary,
            "worker_rows": worker_rows,
            "customer_service_rows": customer_service_rows,
            "summary_unpaid_rows": summary_unpaid_rows,
            "summary_paid_rows": summary_paid_rows,
            "month": month or "",
            "status": normalize_my_payout_status(status),
            "month_options": get_my_payout_month_options(),
        },
    )
