from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

try:
    from web.app.config import config
except Exception:
    config = None


router = APIRouter(tags=["admin_payout_summary"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db_path() -> str:
    if config is not None:
        url = getattr(config, "DATABASE_URL", "")

        if isinstance(url, str) and url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "", 1)

    return str(Path.cwd() / "web_dashboard.db")


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def normalize_role(role: str | None) -> str:
    if role in {"all", "worker", "customer_service"}:
        return role

    return "all"


def build_month_sql(month: str | None, alias: str) -> tuple[str, list[str]]:
    month = (month or "").strip()

    if not month:
        return "", []

    return f" AND strftime('%Y-%m', {alias}.created_at) = ? ", [month]


def empty_person(discord_id: str, display_name: str) -> dict:
    return {
        "discord_id": discord_id,
        "display_name": display_name or discord_id,
        "roles": set(),
        "role_label": "人員",
        "unpaid_total": 0,
        "unpaid_count": 0,
        "items": [],
    }


def add_person(
    people: dict[str, dict],
    *,
    discord_id,
    display_name,
    role: str,
    amount,
    order_no,
    category,
    item,
):
    discord_id = str(discord_id or "").strip()

    if not discord_id:
        return

    person = people.setdefault(
        discord_id,
        empty_person(discord_id, display_name or discord_id),
    )

    if display_name and person["display_name"] == discord_id:
        person["display_name"] = display_name

    amount = int(amount or 0)

    person["roles"].add(role)
    person["unpaid_total"] += amount
    person["unpaid_count"] += 1
    person["items"].append(
        {
            "order_no": order_no,
            "category": category or "",
            "item": item or "",
            "role": "打手" if role == "worker" else "客服",
            "amount": amount,
        }
    )


def finalize_people(people: dict[str, dict], q: str | None) -> list[dict]:
    keyword = (q or "").strip().lower()
    rows = []

    for person in people.values():
        roles = person.pop("roles", set())

        if roles == {"worker"}:
            person["role_label"] = "打手"
        elif roles == {"customer_service"}:
            person["role_label"] = "客服"
        elif roles:
            person["role_label"] = "混合"

        person["items"].sort(
            key=lambda item: str(item["order_no"]),
            reverse=True,
        )

        if keyword:
            haystack = f'{person["display_name"]} {person["discord_id"]}'.lower()

            if keyword not in haystack:
                continue

        rows.append(person)

    return sorted(
        rows,
        key=lambda row: (-int(row["unpaid_total"] or 0), str(row["display_name"] or "")),
    )


def fetch_summary_rows(*, month: str | None, role: str | None, q: str | None) -> tuple[list[dict], dict]:
    role = normalize_role(role)
    people: dict[str, dict] = {}

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row

    try:
        if role in {"all", "worker"}:
            month_sql, params = build_month_sql(month, "p")

            rows = conn.execute(
                f"""
                SELECT
                    p.worker_discord_id AS discord_id,
                    p.worker_display_name AS display_name,
                    p.final_payout AS amount,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payout_status = 'unpaid'
                  {month_sql}
                ORDER BY p.id DESC
                """,
                params,
            ).fetchall()

            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="worker",
                    amount=row["amount"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

        if role in {"all", "customer_service"}:
            month_sql, params = build_month_sql(month, "p")

            rows = conn.execute(
                f"""
                SELECT
                    p.customer_service_discord_id AS discord_id,
                    p.customer_service_display_name AS display_name,
                    p.payout_amount AS amount,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item
                FROM customer_service_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payout_status = 'unpaid'
                  {month_sql}
                ORDER BY p.id DESC
                """,
                params,
            ).fetchall()

            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="customer_service",
                    amount=row["amount"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

    finally:
        conn.close()

    rows = finalize_people(people, q=q)

    totals = {
        "person_count": len(rows),
        "unpaid_total": sum(int(row["unpaid_total"] or 0) for row in rows),
        "unpaid_count": sum(int(row["unpaid_count"] or 0) for row in rows),
    }

    return rows, totals


@router.get("/admin/payouts/summary")
async def admin_payout_summary(
    request: Request,
    month: str | None = "",
    role: str | None = "all",
    q: str | None = "",
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

    role = normalize_role(role)
    month = month or ""
    q = q or ""

    rows, totals = fetch_summary_rows(month=month, role=role, q=q)

    return templates.TemplateResponse(
        request=request,
        name="admin_payout_summary.html",
        context={
            "title": "人員總表",
            "user": user,
            "rows": rows,
            "totals": totals,
            "month": month,
            "role": role,
            "q": q,
        },
    )


@router.get("/admin/payouts/summary.csv")
async def admin_payout_summary_csv(
    request: Request,
    month: str | None = "",
    role: str | None = "all",
    q: str | None = "",
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    rows, totals = fetch_summary_rows(month=month, role=role, q=q)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["身份", "名稱", "Discord ID", "未支付", "筆數"])

    for row in rows:
        writer.writerow([
            row["role_label"],
            row["display_name"],
            row["discord_id"],
            row["unpaid_total"],
            row["unpaid_count"],
        ])

    writer.writerow(["合計", "", "", totals["unpaid_total"], totals["unpaid_count"]])

    data = "\ufeff" + output.getvalue()
    filename = f"payout_unpaid_summary_{month or 'all'}_{role or 'all'}.csv"

    return StreamingResponse(
        iter([data.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
