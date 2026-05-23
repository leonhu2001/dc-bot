from pathlib import Path

ROOT = Path(".")
ROUTERS = ROOT / "web" / "app" / "routers"
TEMPLATES = ROOT / "web" / "app" / "templates"

router_candidates = []
for path in ROUTERS.glob("*.py"):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "/admin/payouts/summary" in text:
        router_candidates.append(path)

if not router_candidates:
    raise RuntimeError("找不到 /admin/payouts/summary 的 router 檔案")

router_path = router_candidates[0]

template_candidates = []
for path in TEMPLATES.glob("*.html"):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "分潤人員總表" in text or ("人員總表" in text and "未發放" in text and "累計" in text):
        template_candidates.append(path)

if template_candidates:
    template_path = template_candidates[0]
else:
    template_path = TEMPLATES / "admin_payout_summary.html"

print("router =", router_path)
print("template =", template_path)

router_path.write_text(r'''
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
'''.strip() + "\n", encoding="utf-8")


template_path.write_text(r'''
{% extends "layout.html" %}

{% block page_title %}人員總表{% endblock %}

{% block content %}
<style>
    .summary-hero {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
    }

    .summary-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }

    .summary-filter-form {
        display: grid;
        grid-template-columns: 180px 180px 1fr auto auto;
        gap: 10px;
        align-items: end;
    }

    .summary-filter-form label {
        display: grid;
        gap: 6px;
    }

    .summary-stat-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
    }

    .summary-stat-card {
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: rgba(15, 23, 42, 0.55);
        border-radius: 14px;
        padding: 16px;
    }

    .summary-stat-card span {
        color: #9ca3af;
        font-size: 13px;
    }

    .summary-stat-card strong {
        display: block;
        margin-top: 6px;
        font-size: 28px;
    }

    .summary-person-list {
        display: grid;
        gap: 12px;
    }

    .summary-person-card {
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: rgba(15, 23, 42, 0.48);
        border-radius: 16px;
        overflow: hidden;
    }

    .summary-person-card summary {
        cursor: pointer;
        list-style: none;
    }

    .summary-person-card summary::-webkit-details-marker {
        display: none;
    }

    .summary-person-head {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 16px;
        padding: 16px;
        align-items: center;
    }

    .summary-person-main {
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 0;
    }

    .summary-avatar {
        width: 44px;
        height: 44px;
        border-radius: 999px;
        display: grid;
        place-items: center;
        background: rgba(99, 102, 241, 0.22);
        border: 1px solid rgba(129, 140, 248, 0.4);
        font-weight: 800;
    }

    .summary-role {
        color: #93c5fd;
        font-size: 13px;
        margin-bottom: 3px;
    }

    .summary-name {
        margin: 0;
        font-size: 18px;
    }

    .summary-id {
        margin: 4px 0 0;
        color: #9ca3af;
        font-size: 13px;
        word-break: break-all;
    }

    .summary-person-money {
        display: flex;
        gap: 10px;
        align-items: center;
    }

    .summary-money-box {
        min-width: 100px;
        border-radius: 12px;
        background: rgba(2, 6, 23, 0.45);
        padding: 10px 12px;
        text-align: right;
    }

    .summary-money-box span {
        display: block;
        color: #9ca3af;
        font-size: 12px;
    }

    .summary-money-box strong {
        display: block;
        margin-top: 3px;
        font-size: 20px;
    }

    .summary-detail {
        border-top: 1px solid rgba(148, 163, 184, 0.18);
        padding: 0 16px 16px;
    }

    .summary-order-row {
        display: grid;
        grid-template-columns: 150px 1fr 80px 100px;
        gap: 10px;
        padding: 10px 0;
        border-bottom: 1px solid rgba(148, 163, 184, 0.12);
        align-items: center;
    }

    .summary-order-row:last-child {
        border-bottom: 0;
    }

    .summary-order-head {
        color: #9ca3af;
        font-size: 13px;
        font-weight: 700;
    }

    .summary-amount {
        text-align: right;
        font-weight: 800;
    }

    @media (max-width: 900px) {
        .summary-hero,
        .summary-person-head {
            grid-template-columns: 1fr;
            display: grid;
        }

        .summary-filter-form,
        .summary-stat-grid {
            grid-template-columns: 1fr;
        }

        .summary-person-money {
            justify-content: stretch;
        }

        .summary-money-box {
            flex: 1;
            text-align: left;
        }

        .summary-order-row {
            grid-template-columns: 1fr;
        }

        .summary-amount {
            text-align: left;
        }
    }
</style>

<section class="panel summary-hero">
    <div>
        <p class="order-no">UNPAID SUMMARY</p>
        <h2>人員總表</h2>
        <p class="muted-text">只顯示未支付分潤，只統計已結單訂單。同一 Discord ID 會合併成一張卡。</p>
    </div>

    <div class="summary-actions">
        <a class="button secondary" href="/admin/payouts/grouped">月結分潤</a>
        <a class="button secondary" href="/admin">回總控</a>
    </div>
</section>

<section class="panel">
    <form method="get" action="/admin/payouts/summary" class="summary-filter-form">
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
        <a class="button secondary" href="/admin/payouts/summary.csv?month={{ month }}&role={{ role }}&q={{ q }}">匯出 CSV</a>
    </form>
</section>

<section class="summary-stat-grid">
    <div class="summary-stat-card">
        <span>未支付總額</span>
        <strong>{{ totals.unpaid_total }}T</strong>
    </div>

    <div class="summary-stat-card">
        <span>未支付人數</span>
        <strong>{{ totals.person_count }}</strong>
    </div>

    <div class="summary-stat-card">
        <span>未支付筆數</span>
        <strong>{{ totals.unpaid_count }}</strong>
    </div>
</section>

<section class="panel">
    <div class="section-title-row">
        <div>
            <h2>未支付名單</h2>
            <p class="muted-text">依未支付金額由高到低排列。點開可以看明細。</p>
        </div>
    </div>

    {% if rows %}
        <div class="summary-person-list">
            {% for row in rows %}
                <details class="summary-person-card" open>
                    <summary class="summary-person-head">
                        <div class="summary-person-main">
                            <div class="summary-avatar">{{ (row.display_name or '?')[:1] }}</div>

                            <div>
                                <div class="summary-role">{{ row.role_label }}</div>
                                <h3 class="summary-name">{{ row.display_name }}</h3>
                                <p class="summary-id">ID：{{ row.discord_id }}</p>
                            </div>
                        </div>

                        <div class="summary-person-money">
                            <div class="summary-money-box">
                                <span>未支付</span>
                                <strong>{{ row.unpaid_total }}T</strong>
                            </div>

                            <div class="summary-money-box">
                                <span>筆數</span>
                                <strong>{{ row.unpaid_count }}</strong>
                            </div>
                        </div>
                    </summary>

                    <div class="summary-detail">
                        <div class="summary-order-row summary-order-head">
                            <div>訂單</div>
                            <div>項目</div>
                            <div>身份</div>
                            <div class="summary-amount">金額</div>
                        </div>

                        {% for item in row.items %}
                            <div class="summary-order-row">
                                <div>{{ item.order_no }}</div>
                                <div>{{ item.category }}｜{{ item.item }}</div>
                                <div>{{ item.role }}</div>
                                <div class="summary-amount">{{ item.amount }}T</div>
                            </div>
                        {% endfor %}
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

print("patched actual payout summary route/template")
