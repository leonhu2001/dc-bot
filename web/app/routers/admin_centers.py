from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from services.ai_support_knowledge import build_knowledge_snapshot
from services.payment_reviews import list_payment_reviews
from services.support_calls import build_support_call_snapshot
from services.ticket_archives import list_ticket_archives
from services.topups import list_topups_for_admin
from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


router = APIRouter(tags=["admin-centers"])

ROOT = Path(__file__).resolve().parents[3]
WEB_DB = ROOT / "web_dashboard.db"
BOT_DB = ROOT / "bot.db"

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_admin(request: Request) -> dict | None:
    user = request.session.get("user")
    if not isinstance(user, dict) or not user.get("is_admin"):
        return None
    return user


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table),),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _staff_snapshot(q: str = "") -> dict[str, Any]:
    if not WEB_DB.exists():
        return {"rows": [], "stats": {}}

    keyword = str(q or "").strip()
    with _connect(WEB_DB) as conn:
        if not _table_exists(conn, "web_staff_members"):
            return {"rows": [], "stats": {}}

        profile_join = (
            "LEFT JOIN staff_profiles p ON p.staff_discord_id = s.discord_id"
            if _table_exists(conn, "staff_profiles")
            else ""
        )
        profile_select = (
            """
            p.profile_type,
            p.role_title,
            p.main_games,
            p.is_public AS profile_public
            """
            if profile_join
            else """
            NULL AS profile_type,
            NULL AS role_title,
            NULL AS main_games,
            NULL AS profile_public
            """
        )

        where = ""
        params: list[Any] = []
        if keyword:
            like = f"%{keyword}%"
            where = """
            WHERE
                s.discord_id LIKE ?
                OR COALESCE(s.display_name, '') LIKE ?
                OR COALESCE(s.global_name, '') LIKE ?
                OR COALESCE(s.username, '') LIKE ?
            """
            params = [like, like, like, like]

        rows = conn.execute(
            f"""
            SELECT
                s.discord_id,
                s.username,
                s.display_name,
                s.global_name,
                s.is_active,
                s.is_customer_service,
                s.is_worker,
                s.is_companion,
                {profile_select}
            FROM web_staff_members s
            {profile_join}
            {where}
            ORDER BY
                COALESCE(s.is_active, 0) DESC,
                COALESCE(s.display_name, s.global_name, s.username, s.discord_id)
            LIMIT 250
            """,
            params,
        ).fetchall()

        stats_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(is_active,0)=1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN COALESCE(is_customer_service,0)=1 THEN 1 ELSE 0 END) AS customer_service,
                SUM(CASE WHEN COALESCE(is_worker,0)=1 THEN 1 ELSE 0 END) AS worker,
                SUM(CASE WHEN COALESCE(is_companion,0)=1 THEN 1 ELSE 0 END) AS companion
            FROM web_staff_members
            """
        ).fetchone()

        profile_total = 0
        profile_public = 0
        if _table_exists(conn, "staff_profiles"):
            profile_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(is_public,1)=1 THEN 1 ELSE 0 END) AS public
                FROM staff_profiles
                """
            ).fetchone()
            profile_total = int(profile_row["total"] or 0)
            profile_public = int(profile_row["public"] or 0)

    return {
        "rows": [dict(row) for row in rows],
        "stats": {
            "total": int(stats_row["total"] or 0),
            "active": int(stats_row["active"] or 0),
            "customer_service": int(stats_row["customer_service"] or 0),
            "worker": int(stats_row["worker"] or 0),
            "companion": int(stats_row["companion"] or 0),
            "profiles": profile_total,
            "public_profiles": profile_public,
        },
    }


def _customer_snapshot(q: str = "") -> dict[str, Any]:
    if not WEB_DB.exists():
        return {"rows": [], "reviews": [], "stats": {}}

    keyword = str(q or "").strip()

    with _connect(WEB_DB) as conn:
        if not _table_exists(conn, "web_orders"):
            return {"rows": [], "reviews": [], "stats": {}}

        cols = _columns(conn, "web_orders")
        pay_expr = (
            "COALESCE(customer_pay_amount, amount, 0)"
            if "customer_pay_amount" in cols
            else "COALESCE(amount, 0)"
        )

        where = "WHERE COALESCE(customer_discord_id,'') <> ''"
        params: list[Any] = []
        if keyword:
            like = f"%{keyword}%"
            where += """
              AND (
                    customer_discord_id LIKE ?
                 OR COALESCE(customer_display_name,'') LIKE ?
              )
            """
            params.extend([like, like])

        rows = conn.execute(
            f"""
            SELECT
                customer_discord_id,
                MAX(COALESCE(NULLIF(customer_display_name,''), customer_discord_id)) AS customer_display_name,
                COUNT(*) AS order_count,
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status,'')) IN ('closed','completed','done')
                        THEN {pay_expr}
                        ELSE 0
                    END
                ) AS completed_spend,
                MAX(COALESCE(updated_at, created_at)) AS last_seen_at
            FROM web_orders
            {where}
            GROUP BY customer_discord_id
            ORDER BY last_seen_at DESC
            LIMIT 250
            """,
            params,
        ).fetchall()

        total_customers = conn.execute(
            """
            SELECT COUNT(DISTINCT customer_discord_id)
            FROM web_orders
            WHERE COALESCE(customer_discord_id,'') <> ''
            """
        ).fetchone()[0]

        review_rows: list[sqlite3.Row] = []
        if _table_exists(conn, "order_reviews"):
            review_rows = conn.execute(
                """
                SELECT
                    id,
                    customer_discord_id,
                    customer_display_name,
                    staff_discord_id,
                    staff_display_name,
                    rating,
                    comment,
                    service_item,
                    is_public,
                    is_hidden,
                    created_at
                FROM order_reviews
                ORDER BY id DESC
                LIMIT 12
                """
            ).fetchall()

            review_stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(is_public,1)=1 AND COALESCE(is_hidden,0)=0 THEN 1 ELSE 0 END) AS visible
                FROM order_reviews
                """
            ).fetchone()
        else:
            review_stats = {"total": 0, "visible": 0}

    wallet_map: dict[str, int] = {}
    wallet_count = 0
    wallet_total = 0
    if BOT_DB.exists():
        try:
            with _connect(BOT_DB) as bot:
                if _table_exists(bot, "customer_wallets"):
                    wallet_rows = bot.execute(
                        "SELECT customer_discord_id, balance FROM customer_wallets"
                    ).fetchall()
                    wallet_map = {
                        str(row["customer_discord_id"]): int(row["balance"] or 0)
                        for row in wallet_rows
                    }
                    wallet_count = len(wallet_rows)
                    wallet_total = sum(wallet_map.values())
        except sqlite3.Error:
            pass

    result_rows = []
    for row in rows:
        item = dict(row)
        customer_id = str(item.get("customer_discord_id") or "")
        item["wallet_balance"] = int(wallet_map.get(customer_id, 0))
        result_rows.append(item)

    return {
        "rows": result_rows,
        "reviews": [dict(row) for row in review_rows],
        "stats": {
            "customers": int(total_customers or 0),
            "wallet_count": wallet_count,
            "wallet_total": wallet_total,
            "review_count": int(review_stats["total"] or 0),
            "visible_reviews": int(review_stats["visible"] or 0),
        },
    }


def _payout_snapshot() -> dict[str, int]:
    result = {
        "unpaid_total": 0,
        "unpaid_count": 0,
        "paid_total": 0,
        "paid_count": 0,
    }

    if not WEB_DB.exists():
        return result

    with _connect(WEB_DB) as conn:
        specs = (
            ("worker_payouts", "final_payout"),
            ("customer_service_payouts", "payout_amount"),
            ("worker_tips", "amount"),
        )
        for table, amount_col in specs:
            if not _table_exists(conn, table):
                continue
            cols = _columns(conn, table)
            if amount_col not in cols or "payout_status" not in cols:
                continue

            row = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN payout_status='unpaid' THEN COALESCE({amount_col},0) ELSE 0 END) AS unpaid_total,
                    SUM(CASE WHEN payout_status='unpaid' THEN 1 ELSE 0 END) AS unpaid_count,
                    SUM(CASE WHEN payout_status='paid' THEN COALESCE({amount_col},0) ELSE 0 END) AS paid_total,
                    SUM(CASE WHEN payout_status='paid' THEN 1 ELSE 0 END) AS paid_count
                FROM {table}
                """
            ).fetchone()

            for key in result:
                result[key] += int(row[key] or 0)

    return result


def _finance_snapshot(*, is_manager: bool) -> dict[str, Any]:
    reviews = [dict(row) for row in list_payment_reviews(limit=300)]
    topups = [dict(row) for row in list_topups_for_admin(limit=300)]

    entries = []
    for item in reviews:
        item = dict(item)
        item["kind"] = str(item.get("source_type") or "payment")
        item["display_no"] = str(item.get("review_no") or f"PAY-{item.get('id')}")
        item["is_pending"] = str(item.get("status") or "") in {
            "pending_review",
            "apply_error",
            "approved_pending_apply",
        }
        entries.append(item)

    for item in topups:
        item = dict(item)
        item["kind"] = "topup"
        item["display_no"] = str(item.get("topup_no") or f"TOPUP-{item.get('id')}")
        item["is_pending"] = str(item.get("status") or "") in {
            "pending_review",
            "approved_pending_credit",
            "crediting",
        }
        entries.append(item)

    entries.sort(
        key=lambda item: str(
            item.get("updated_at")
            or item.get("created_at")
            or ""
        ),
        reverse=True,
    )

    accounting = None
    if is_manager:
        accounting = build_accounting_reconciliation_snapshot(detail_limit=0)

    return {
        "payments": entries[:20],
        "pending_payment_count": sum(1 for item in entries if item["is_pending"]),
        "payout": _payout_snapshot(),
        "accounting": accounting,
    }


def _support_snapshot(*, is_manager: bool) -> dict[str, Any]:
    support = build_support_call_snapshot(days=30)
    tickets = list_ticket_archives(limit=15)
    knowledge = build_knowledge_snapshot() if is_manager else None

    return {
        "support": support,
        "tickets": tickets,
        "knowledge": knowledge,
    }


async def _render(
    request: Request,
    *,
    center: str,
    q: str = "",
):
    user = _current_admin(request)
    if user is None:
        return RedirectResponse("/no-access", status_code=303)

    is_manager = bool(user.get("is_manager"))

    if center == "staff":
        snapshot = await run_in_threadpool(_staff_snapshot, q)
        title = "人員中心"
    elif center == "customers":
        snapshot = await run_in_threadpool(_customer_snapshot, q)
        title = "客戶中心"
    elif center == "finance":
        snapshot = await run_in_threadpool(
            lambda: _finance_snapshot(is_manager=is_manager)
        )
        title = "財務中心"
    elif center == "support":
        snapshot = await run_in_threadpool(
            lambda: _support_snapshot(is_manager=is_manager)
        )
        title = "客服中心"
    else:
        return RedirectResponse("/admin", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin_center.html",
        context={
            "title": title,
            "user": user,
            "center": center,
            "snapshot": snapshot,
            "q": str(q or "").strip(),
            "is_manager": is_manager,
        },
    )


@router.get("/admin/staff-center")
async def staff_center(request: Request, q: str = ""):
    return await _render(request, center="staff", q=q)


@router.get("/admin/customer-center")
async def customer_center(request: Request, q: str = ""):
    return await _render(request, center="customers", q=q)


@router.get("/admin/finance-center")
async def finance_center(request: Request):
    return await _render(request, center="finance")


@router.get("/admin/support-center")
async def support_center(request: Request):
    return await _render(request, center="support")
