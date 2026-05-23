from pathlib import Path

ROUTER = Path("web/app/routers/admin_payout_summary.py")
TEMPLATE = Path("web/app/templates/admin_payout_summary.html")

ROUTER.parent.mkdir(parents=True, exist_ok=True)
TEMPLATE.parent.mkdir(parents=True, exist_ok=True)

ROUTER.write_text(r'''
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout

router = APIRouter(tags=["admin-payout-summary"])

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


def parse_month_range(month: str | None) -> tuple[datetime | None, datetime | None]:
    if not month:
        return None, None

    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return None, None

    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)

    return start, end


def apply_month_filter(statement, payout_model, month: str | None):
    start, end = parse_month_range(month)

    if start is not None:
        statement = statement.where(payout_model.created_at >= start)

    if end is not None:
        statement = statement.where(payout_model.created_at < end)

    return statement


def empty_person_row(discord_id: str, display_name: str) -> dict:
    return {
        "discord_id": str(discord_id or ""),
        "display_name": display_name or str(discord_id or ""),
        "roles": set(),
        "role_label": "人員",
        "unpaid_total": 0,
        "unpaid_count": 0,
        "items": [],
    }


def add_person_item(rows_by_id: dict[str, dict], *, discord_id, display_name, role, amount, order, created_at):
    discord_id = str(discord_id or "").strip()

    if not discord_id:
        return

    row = rows_by_id.setdefault(
        discord_id,
        empty_person_row(discord_id=discord_id, display_name=display_name or discord_id),
    )

    if display_name and row["display_name"] == discord_id:
        row["display_name"] = display_name

    row["roles"].add(role)
    row["unpaid_total"] += int(amount or 0)
    row["unpaid_count"] += 1

    row["items"].append(
        {
            "order_no": getattr(order, "bot_order_no", None) or f"WEB-{getattr(order, 'id', '')}",
            "category": getattr(order, "category", "") or "",
            "item": getattr(order, "item", "") or "",
            "amount": int(amount or 0),
            "created_at": created_at,
            "role": "打手" if role == "worker" else "客服",
        }
    )


def finalize_rows(rows_by_id: dict[str, dict], q: str | None) -> list[dict]:
    keyword = (q or "").strip().lower()
    rows = []

    for row in rows_by_id.values():
        roles = row.pop("roles", set())

        if roles == {"worker"}:
            row["role_label"] = "打手"
        elif roles == {"customer_service"}:
            row["role_label"] = "客服"
        elif roles:
            row["role_label"] = "混合"

        row["items"].sort(
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

        if keyword:
            haystack = f'{row["display_name"]} {row["discord_id"]}'.lower()

            if keyword not in haystack:
                continue

        rows.append(row)

    return sorted(
        rows,
        key=lambda item: (-int(item["unpaid_total"] or 0), str(item["display_name"] or "")),
    )


def build_summary_rows(*, month: str | None, role: str | None, q: str | None) -> tuple[list[dict], dict]:
    rows_by_id: dict[str, dict] = {}

    db = SessionLocal()

    try:
        if role in {None, "", "all", "worker"}:
            statement = (
                select(WorkerPayout, WebOrder)
                .join(WebOrder, WebOrder.id == WorkerPayout.order_id)
                .where(WebOrder.status == "closed")
                .where(WorkerPayout.payout_status == PayoutStatus.UNPAID.value)
            )
            statement = apply_month_filter(statement, WorkerPayout, month)

            for payout, order in db.execute(statement).all():
                add_person_item(
                    rows_by_id,
                    discord_id=payout.worker_discord_id,
                    display_name=payout.worker_display_name or str(payout.worker_discord_id),
                    role="worker",
                    amount=payout.final_payout,
                    order=order,
                    created_at=payout.created_at,
                )

        if role in {None, "", "all", "customer_service"}:
            statement = (
                select(CustomerServicePayout, WebOrder)
                .join(WebOrder, WebOrder.id == CustomerServicePayout.order_id)
                .where(WebOrder.status == "closed")
                .where(CustomerServicePayout.payout_status == PayoutStatus.UNPAID.value)
            )
            statement = apply_month_filter(statement, CustomerServicePayout, month)

            for payout, order in db.execute(statement).all():
                add_person_item(
                    rows_by_id,
                    discord_id=payout.customer_service_discord_id,
                    display_name=payout.customer_service_display_name or str(payout.customer_service_discord_id),
                    role="customer_service",
                    amount=payout.payout_amount,
                    order=order,
                    created_at=payout.created_at,
                )
    finally:
        db.close()

    rows = finalize_rows(rows_by_id, q=q)

    totals = {
        "unpaid_total": sum(row["unpaid_total"] for row in rows),
        "unpaid_count": sum(row["unpaid_count"] for row in rows),
        "person_count": len(rows),
    }

    return rows, totals


@router.get("/admin/payouts/summary")
async def admin_payout_summary(
    request: Request,
    month: str | None = None,
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

    role = role if role in {"all", "worker", "customer_service"} else "all"
    month = month or ""
    q = q or ""

    rows, totals = build_summary_rows(month=month, role=role, q=q)

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
    month: str | None = None,
    role: str | None = "all",
    q: str | None = "",
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    role = role if role in {"all", "worker", "customer_service"} else "all"
    rows, totals = build_summary_rows(month=month, role=role, q=q)

    lines = [
        "身份,Discord ID,名稱,未支付總額,未支付筆數"
    ]

    for row in rows:
        values = [
            row["role_label"],
            row["discord_id"],
            row["display_name"],
            str(row["unpaid_total"]),
            str(row["unpaid_count"]),
        ]
        safe_values = [value.replace('"', '""') for value in values]
        lines.append(",".join(f'"{value}"' for value in safe_values))

    lines.append(
        f'"合計","","","{totals["unpaid_total"]}","{totals["unpaid_count"]}"'
    )

    csv_text = "\ufeff" + "\n".join(lines) + "\n"
    filename = f"payout_unpaid_summary_{month or 'all'}_{role or 'all'}.csv"

    return StreamingResponse(
        iter([csv_text.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
'''.strip() + "\n", encoding="utf-8")


TEMPLATE.write_text(r'''
{% extends "layout.html" %}

{% block page_title %}人員總表{% endblock %}

{% block content %}
    <section class="payout-hero panel">
        <div class="payout-hero-main">
            <p class="order-no">UNPAID SUMMARY</p>
            <h2>人員總表</h2>
            <p class="muted-text">只顯示未支付分潤，且只統計已結單訂單。同一個 Discord ID 會合併顯示。</p>
        </div>

        <div class="payout-hero-actions">
            <a class="button secondary" href="/admin/payouts/grouped">月結分潤</a>
            <a class="button secondary" href="/admin/payouts">分潤明細</a>
            <a class="button secondary" href="/admin">回總控</a>
        </div>
    </section>

    <section class="panel payout-filter-panel">
        <form method="get" action="/admin/payouts/summary" class="payout-filter-form">
            <label>
                <span>月份</span>
                <input class="input" type="month" name="month" value="{{ month }}">
            </label>

            <label>
                <span>身份</span>
                <select class="input" name="role">
                    <option value="all" {% if role == "all" %}selected{% endif %}>全部</option>
                    <option value="worker" {% if role == "worker" %}selected{% endif %}>打手</option>
                    <option value="customer_service" {% if role == "customer_service" %}selected{% endif %}>客服</option>
                </select>
            </label>

            <label>
                <span>搜尋</span>
                <input class="input" type="text" name="q" value="{{ q }}" placeholder="名稱或 Discord ID">
            </label>

            <button class="button" type="submit">套用篩選</button>

            <a
                class="button secondary"
                href="/admin/payouts/summary.csv?month={{ month }}&role={{ role }}&q={{ q }}"
            >
                匯出 CSV
            </a>
        </form>
    </section>

    <section class="payout-stat-grid">
        <div class="payout-stat-card highlight-unpaid">
            <span>未支付總額</span>
            <strong>{{ totals.unpaid_total }}T</strong>
        </div>

        <div class="payout-stat-card">
            <span>未支付人數</span>
            <strong>{{ totals.person_count }}</strong>
        </div>

        <div class="payout-stat-card">
            <span>未支付筆數</span>
            <strong>{{ totals.unpaid_count }}</strong>
        </div>
    </section>

    <section class="panel payout-group-panel">
        <div class="section-title-row">
            <div>
                <h2>未支付名單</h2>
                <p class="muted-text">依金額由高到低排列。點開人員可以看明細。</p>
            </div>
        </div>

        {% if rows %}
            <div class="payout-person-list">
                {% for row in rows %}
                    <details class="payout-person-card" open>
                        <summary class="payout-person-summary">
                            <div class="person-left">
                                <div class="person-avatar">{{ (row.display_name or '?')[:1] }}</div>
                                <div>
                                    <div class="person-role">{{ row.role_label }}</div>
                                    <h3>{{ row.display_name }}</h3>
                                    <p>ID：{{ row.discord_id }}</p>
                                </div>
                            </div>

                            <div class="person-totals">
                                <div>
                                    <span>未支付</span>
                                    <strong class="text-unpaid">{{ row.unpaid_total }}T</strong>
                                </div>

                                <div>
                                    <span>筆數</span>
                                    <strong>{{ row.unpaid_count }}</strong>
                                </div>
                            </div>
                        </summary>

                        <div class="payout-person-body">
                            <div class="payout-order-list">
                                <div class="payout-order-header">
                                    <span>訂單</span>
                                    <span>項目</span>
                                    <span>身份</span>
                                    <span>金額</span>
                                </div>

                                {% for item in row.items %}
                                    <div class="payout-order-row">
                                        <div class="order-no-cell">{{ item.order_no }}</div>
                                        <div>{{ item.category }}｜{{ item.item }}</div>
                                        <div>{{ item.role }}</div>
                                        <div class="amount-cell">{{ item.amount }}T</div>
                                    </div>
                                {% endfor %}
                            </div>
                        </div>
                    </details>
                {% endfor %}
            </div>
        {% else %}
            <div class="empty-state">目前沒有未支付分潤。</div>
        {% endif %}
    </section>
{% endblock %}
'''.strip() + "\n", encoding="utf-8")

print("patched admin payout summary: unpaid only + card layout + merged Discord ID")
