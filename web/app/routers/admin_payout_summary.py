from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

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


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin(request: Request) -> dict | None:
    user = current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


def normalize_role(role: str | None) -> str:
    return role if role in {"all", "worker", "customer_service"} else "all"


def payout_order_date_expr(alias: str = "w") -> str:
    """人員總表使用的有效結單日期：closed_at -> updated_at -> created_at。"""
    return (
        f"COALESCE("
        f"NULLIF({alias}.closed_at, ''), "
        f"NULLIF({alias}.updated_at, ''), "
        f"NULLIF({alias}.created_at, '')"
        f")"
    )


def month_filter_sql(month: str | None, alias: str) -> tuple[str, list[str]]:
    month = (month or "").strip()

    if not month:
        return "", []

    return f" AND substr({payout_order_date_expr(alias)}, 1, 7) = ? ", [month]


def add_person(people: dict[str, dict], *, discord_id, display_name, role, amount, order_no, category, item, payout_status, customer_name=None, closed_at=None):
    discord_id = str(discord_id or "").strip()
    if not discord_id:
        return

    payout_status = "paid" if payout_status == "paid" else "unpaid"

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

    customer_name = str(customer_name or "").strip() or "未紀錄"
    closed_text = str(closed_at or "").strip()
    closed_date = closed_text[:10] if closed_text else "未紀錄"

    if display_name and person["display_name"] == discord_id:
        person["display_name"] = display_name

    amount = int(amount or 0)
    person["roles"].add(role)

    if payout_status == "paid":
        person["paid_total"] += amount
        person["paid_count"] += 1
    else:
        person["unpaid_total"] += amount
        person["unpaid_count"] += 1

    person["items"].append({
        "order_no": order_no,
        "category": category or "",
        "item": item or "",
        "customer_name": customer_name,
        "closed_date": closed_date,
        "role": "護級 / 陪級" if role == "worker" else "客服",
        "amount": amount,
        "payout_status": payout_status,
        "status_label": "已支付" if payout_status == "paid" else "未支付",
    })


def finalize_people(people: dict[str, dict], q: str | None, status: str | None = "unpaid") -> list[dict]:
    keyword = (q or "").strip().lower()
    status = normalize_payout_status(status)
    rows = []

    for person in people.values():
        roles = person.pop("roles", set())

        if roles == {"worker"}:
            person["role_label"] = "護級 / 陪級"
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
            if int(person.get("paid_total") or 0) <= 0 and int(person.get("unpaid_total") or 0) <= 0:
                continue
            person["display_total"] = int(person.get("unpaid_total") or 0) + int(person.get("paid_total") or 0)
            person["display_count"] = int(person.get("unpaid_count") or 0) + int(person.get("paid_count") or 0)
            person["display_status"] = "全部"
        else:
            if int(person.get("unpaid_total") or 0) <= 0:
                continue
            person["display_total"] = person["unpaid_total"]
            person["display_count"] = person["unpaid_count"]
            person["display_status"] = "未支付"

        person["items"].sort(key=lambda x: x["order_no"], reverse=True)

        if keyword:
            haystack = f'{person["display_name"]} {person["discord_id"]}'.lower()
            if keyword not in haystack:
                continue

        rows.append(person)

    return sorted(rows, key=lambda x: (-int(x.get("display_total") or 0), x["display_name"]))



def normalize_payout_status(status: str | None) -> str:
    status = str(status or "unpaid").strip()

    if status in {"paid", "已發放", "已支付"}:
        return "paid"

    if status in {"all", "全部", "全部狀態"}:
        return "all"

    return "unpaid"


def fetch_rows(month: str | None, role: str | None, q: str | None, status: str | None = "unpaid"):
    role = normalize_role(role)
    status = normalize_payout_status(status)
    people: dict[str, dict] = {}

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row

    payout_status_sql = ""
    payout_status_params = []

    if status in {"unpaid", "paid"}:
        payout_status_sql = " AND p.payout_status = ? "
        payout_status_params.append(status)

    try:
        if role in {"all", "worker"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(f"""
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
                    COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND COALESCE(p.final_payout, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
            """, [*payout_status_params, *params]).fetchall()

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

        if role in {"all", "customer_service"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(f"""
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
                    COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
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
            """, [*payout_status_params, *params]).fetchall()

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


def summary_db_path() -> str:
    from pathlib import Path
    return str(Path.cwd() / "web_dashboard.db")


def get_summary_month_options() -> list[dict]:
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

        options.append({"value": value, "label": label})

    return options


def normalize_summary_month(month: str | None) -> str:
    return str(month or "").strip()


def build_summary_bulk_redirect(month: str | None, status: str | None, role: str | None) -> str:
    from urllib.parse import urlencode

    query = {}

    if month:
        query["month"] = month

    # 操作完回到目前身份，但狀態切成目標頁面會由 route 控制
    if role:
        query["role"] = role

    return "/admin/payouts/summary?" + urlencode(query)


def update_summary_payout_status(month: str | None, role: str | None, target_status: str) -> None:
    """依人員總表目前月份/身份篩選，批量標記分潤狀態。"""
    month = normalize_summary_month(month)
    role = str(role or "all").strip()
    target_status = "paid" if target_status == "paid" else "unpaid"

    paid_at_sql = "datetime('now')" if target_status == "paid" else "NULL"

    conn = sqlite3.connect(summary_db_path())

    try:
        order_filter = "w.status = 'closed'"
        params = []

        if month:
            order_filter += " AND substr(COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            params.append(month)

        # 護級 / 陪級
        if role in {"all", "", "worker", "護級 / 陪級"}:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?,
                    paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id
                    FROM web_orders w
                    WHERE {order_filter}
                )
                """,
                [target_status, *params],
            )

        # 客服
        if role in {"all", "", "customer_service", "客服"}:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?,
                    paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id
                    FROM web_orders w
                    WHERE {order_filter}
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



def update_summary_person_payout_status(month: str, person_role: str, person_id: str, target_status: str):
    """更新單一人員分潤狀態。

    混合身分要同時更新護級 / 陪級分潤與魔丸♫客服分潤。
    """
    person_id = str(person_id or "").strip()
    if not person_id:
        return

    target_status = "paid" if str(target_status or "").strip() == "paid" else "unpaid"
    paid_at_sql = "datetime('now', '+8 hours')" if target_status == "paid" else "NULL"

    role_text = str(person_role or "").strip().lower()

    update_worker = role_text in {
        "worker",
        "護級 / 陪級",
        "worker_payout",
        "護級 / 陪級分潤",
        "mixed",
        "mix",
        "both",
        "hybrid",
        "混合",
        "混合身分",
        "客服 / 護級",
        "護級 / 客服",
        "總控 / 客服 / 護級",
    }

    update_customer_service = role_text in {
        "customer_service",
        "customer-service",
        "cs",
        "客服",
        "魔丸♫客服分潤",
        "mixed",
        "mix",
        "both",
        "hybrid",
        "混合",
        "混合身分",
        "客服 / 護級",
        "護級 / 客服",
        "總控 / 客服 / 護級",
    }

    # 有些舊資料 role_label 可能只寫「混合」或畫面顯示「混合」，
    # 保底：只要不是明確客服或明確護級 / 陪級，就兩邊都嘗試更新。
    if not update_worker and not update_customer_service:
        update_worker = True
        update_customer_service = True

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row

    try:
        order_filter = "w.status = 'closed'"
        params_worker = [target_status, person_id]
        params_cs = [target_status, person_id]

        if month:
            order_filter += " AND substr(COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            params_worker.append(month)
            params_cs.append(month)

        if update_worker:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?,
                    paid_at = {paid_at_sql}
                WHERE worker_discord_id = ?
                  AND order_id IN (
                      SELECT w.id
                      FROM web_orders w
                      WHERE {order_filter}
                  )
                """,
                params_worker,
            )

        if update_customer_service:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?,
                    paid_at = {paid_at_sql}
                WHERE customer_service_discord_id = ?
                  AND order_id IN (
                      SELECT w.id
                      FROM web_orders w
                      WHERE {order_filter}
                  )
                """,
                params_cs,
            )

        conn.commit()

    finally:
        conn.close()

def build_combined_summary_rows(unpaid_rows: list[dict], paid_rows: list[dict]) -> list[dict]:
    """人員總表用：把未發放與已發放同一人合併成一列。"""
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
    """把 web_staff_members.avatar 接到人員總表 row。"""
    discord_ids = []
    for row in rows or []:
        discord_id = str(row.get("discord_id") or "").strip()
        if discord_id:
            discord_ids.append(discord_id)

    if not discord_ids:
        return rows

    conn = sqlite3.connect(summary_db_path())
    conn.row_factory = sqlite3.Row

    try:
        placeholders = ",".join("?" for _ in discord_ids)
        avatar_rows = conn.execute(
            f"""
            SELECT discord_id, avatar
            FROM web_staff_members
            WHERE discord_id IN ({placeholders})
            """,
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
            row["avatar_url"] = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.{ext}?size=128"
        else:
            row["avatar_url"] = ""

    return rows


@router.get("/admin/payouts/summary")
async def admin_payout_summary(request: Request, month: str | None = "", role: str | None = "all", q: str | None = ""):
    user = require_admin(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": current_user(request),
            },
            status_code=403,
        )

    role = normalize_role(role)
    status = "all"
    if status not in {"unpaid", "paid", "all"}:
        status = "unpaid"

    status = "unpaid"
    rows, totals = fetch_rows(month, role, q, status)
    unpaid_rows, unpaid_totals = fetch_rows(month, role, q, "unpaid")
    paid_rows, paid_totals = fetch_rows(month, role, q, "paid")
    summary_rows = attach_staff_avatars_to_summary_rows(build_combined_summary_rows(unpaid_rows, paid_rows))

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
async def admin_payout_summary_csv(request: Request, month: str | None = "", role: str | None = "all", q: str | None = ""):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    rows, totals = fetch_rows(month, role, q, status)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["身份", "名稱", "Discord ID", "未支付", "筆數"])

    for row in rows:
        writer.writerow([row["role_label"], row["display_name"], row["discord_id"], row["unpaid_total"], row["unpaid_count"]])

    writer.writerow(["合計", "", "", totals["unpaid_total"], totals["unpaid_count"]])

    data = "\ufeff" + output.getvalue()

    return StreamingResponse(
        iter([data.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="payout_unpaid_summary.csv"'},
    )



@router.get("/admin/month-options")
async def admin_month_options(request: Request):
    """回傳有訂單資料的月份，給所有後台月份欄位改成下拉選單。"""
    user = require_admin(request) if "require_admin" in globals() else require_admin_user(request)

    if not user:
        return JSONResponse({"ok": False, "months": []}, status_code=403)

    conn = sqlite3.connect(db_path() if "db_path" in globals() else get_db_path())
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

    months = []

    for row in rows:
        value = str(row["month_value"] or "").strip()

        if not value:
            continue

        try:
            year, month = value.split("-", 1)
            label = f"{int(year)}年{int(month)}月"
        except Exception:
            label = value

        months.append(
            {
                "value": value,
                "label": label,
            }
        )

    return {
        "ok": True,
        "months": months,
    }


@router.post("/admin/payouts/summary/mark-paid")
async def mark_summary_payouts_paid(request: Request):
    user = request.session.get("user")

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    month = str(form.get("month") or "").strip()
    role = str(form.get("role") or "all").strip()

    update_summary_payout_status(month, role, "paid")

    return RedirectResponse(url=build_summary_bulk_redirect(month, "paid", role), status_code=303)


@router.post("/admin/payouts/summary/mark-unpaid")
async def mark_summary_payouts_unpaid(request: Request):
    user = request.session.get("user")

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    month = str(form.get("month") or "").strip()
    role = str(form.get("role") or "all").strip()

    update_summary_payout_status(month, role, "unpaid")

    return RedirectResponse(url=build_summary_bulk_redirect(month, "unpaid", role), status_code=303)


@router.post("/admin/payouts/summary/person-status")
async def update_summary_person_status(request: Request):
    user = request.session.get("user")

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()

    month = str(form.get("month") or "").strip()
    current_role = str(form.get("current_role") or "all").strip()
    person_role = str(form.get("person_role") or "").strip()
    person_id = str(form.get("person_id") or "").strip()
    target_status = str(form.get("target_status") or "unpaid").strip()

    update_summary_person_payout_status(month, person_role, person_id, target_status)

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

