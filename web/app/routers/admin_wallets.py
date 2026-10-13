from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.wallet_refunds import (
    create_wallet_refund_request,
    list_customer_wallet_refunds,
)
from services.wallet_service import ensure_wallet_tables as ensure_wallet_service_tables
from web.app.routers.admin_staff import require_admin


router = APIRouter(prefix="/admin/wallets", tags=["admin-wallets"])
templates = Jinja2Templates(directory="web/app/templates")


def bot_db_path() -> Path:
    return Path("/opt/dc-bot/bot.db")


def web_dashboard_db_path() -> Path:
    return Path("/opt/dc-bot/web_dashboard.db")


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def fetch_customer_display_names(customer_ids: list[str]) -> dict[str, str]:
    clean_ids = [str(x) for x in customer_ids if str(x or "").strip()]
    if not clean_ids:
        return {}

    db_path = web_dashboard_db_path()
    if not db_path.exists():
        return {}

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cols = _table_columns(conn, "web_orders")
            if "customer_discord_id" not in cols:
                return {}

            name_candidates = [
                "customer_display_name",
                "customer_name",
                "customer_nickname",
                "customer_username",
            ]
            name_col = next((col for col in name_candidates if col in cols), None)
            if name_col is None:
                return {}

            order_col = "id" if "id" in cols else "rowid"
            placeholders = ",".join("?" for _ in clean_ids)
            rows = conn.execute(
                f"""
                SELECT customer_discord_id, {name_col} AS display_name,
                       MAX({order_col}) AS latest_id
                FROM web_orders
                WHERE customer_discord_id IN ({placeholders})
                  AND {name_col} IS NOT NULL
                  AND TRIM({name_col}) != ''
                GROUP BY customer_discord_id
                """,
                clean_ids,
            ).fetchall()

            result = {}
            for row in rows:
                customer_id = str(row["customer_discord_id"] or "")
                display_name = str(row["display_name"] or "").strip()
                if customer_id and display_name:
                    result[customer_id] = display_name
            return result
    except sqlite3.Error:
        return {}


def format_t_amount(amount: int | None) -> str:
    try:
        value = int(amount or 0)
    except (TypeError, ValueError):
        value = 0
    return f"{value:,}T"


def format_wallet_datetime(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"

    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        pass

    text = text.replace("T", " ")
    if "+" in text:
        text = text.split("+", 1)[0]
    if len(text) >= 16:
        text = text[:16]
    return text.replace("-", "/")


def wallet_type_label(tx_type: str | None) -> str:
    mapping = {
        "topup": "儲值本金",
        "topup_bonus": "VIP 儲值贈額",
        "topup_bonus_legacy": "舊制儲值回饋",
        "payment": "訂單扣款",
        "tip_payment": "雞腿扣款",
        "refund": "儲值退款",
        "bonus_reversal": "退款撤銷贈額",
        "topup_bonus_reversal": "撤銷儲值贈額",
        "adjustment": "修正",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def ensure_wallet_tables() -> None:
    ensure_wallet_service_tables(bot_db_path())


def _decorate_wallet(data: dict) -> dict:
    principal = max(0, int(data.get("principal_balance") or 0))
    refund_offset = max(0, int(data.get("refund_offset_balance") or 0))
    data["refundable_balance"] = max(0, principal - refund_offset)
    data["balance_text"] = format_t_amount(data.get("balance"))
    data["principal_balance_text"] = format_t_amount(principal)
    data["bonus_balance_text"] = format_t_amount(data.get("bonus_balance"))
    data["refund_offset_balance_text"] = format_t_amount(refund_offset)
    data["refundable_balance_text"] = format_t_amount(data["refundable_balance"])
    data["updated_at_text"] = format_wallet_datetime(data.get("updated_at"))
    return data


def fetch_wallets(keyword: str | None = None) -> list[dict]:
    ensure_wallet_tables()
    q = str(keyword or "").strip()

    sql = """
        SELECT
            w.customer_discord_id,
            w.balance,
            w.principal_balance,
            w.bonus_balance,
            w.refund_offset_balance,
            w.updated_at,
            (
                SELECT COUNT(*)
                FROM wallet_transactions t
                WHERE t.customer_discord_id = w.customer_discord_id
            ) AS transaction_count,
            (
                SELECT t.note
                FROM wallet_transactions t
                WHERE t.customer_discord_id = w.customer_discord_id
                  AND t.note IS NOT NULL
                  AND TRIM(t.note) != ''
                ORDER BY t.id DESC
                LIMIT 1
            ) AS last_note,
            (
                SELECT t.operator_display_name
                FROM wallet_transactions t
                WHERE t.customer_discord_id = w.customer_discord_id
                  AND t.operator_display_name IS NOT NULL
                  AND TRIM(t.operator_display_name) != ''
                ORDER BY t.id DESC
                LIMIT 1
            ) AS last_operator
        FROM customer_wallets w
    """

    params: list[str] = []
    if q:
        like = f"%{q}%"
        sql += """
            WHERE w.customer_discord_id LIKE ?
               OR EXISTS (
                    SELECT 1
                    FROM wallet_transactions t
                    WHERE t.customer_discord_id = w.customer_discord_id
                      AND (
                            t.note LIKE ?
                         OR t.order_no LIKE ?
                         OR t.operator_display_name LIKE ?
                      )
               )
        """
        params.extend([like, like, like, like])

    sql += " ORDER BY w.updated_at DESC, CAST(w.balance AS INTEGER) DESC"

    with sqlite3.connect(bot_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    customer_ids = [str(row["customer_discord_id"]) for row in rows]
    display_names = fetch_customer_display_names(customer_ids)
    wallets = []
    for row in rows:
        data = dict(row)
        customer_id = str(data.get("customer_discord_id") or "")
        data["customer_display_name"] = (
            display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
        )
        wallets.append(_decorate_wallet(data))
    return wallets


def fetch_wallet_detail(
    customer_discord_id: str,
    limit: int = 100,
) -> tuple[dict, list[dict]]:
    """Keep the long-standing two-value helper contract for callers/tests."""
    ensure_wallet_tables()
    safe_limit = max(1, min(int(limit or 100), 300))

    with sqlite3.connect(bot_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        wallet_row = conn.execute(
            """
            SELECT customer_discord_id, balance, principal_balance,
                   bonus_balance, refund_offset_balance, updated_at
            FROM customer_wallets
            WHERE customer_discord_id = ?
            """,
            (str(customer_discord_id),),
        ).fetchone()

        tx_rows = conn.execute(
            """
            SELECT
                id, customer_discord_id, amount, balance_before, balance_after,
                type, order_channel_id, order_no, operator_discord_id,
                operator_display_name, note, created_at
            FROM wallet_transactions
            WHERE customer_discord_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_discord_id), safe_limit),
        ).fetchall()

    if wallet_row is not None:
        wallet = dict(wallet_row)
    else:
        latest_tx = tx_rows[0] if tx_rows else None
        balance = int(latest_tx["balance_after"] or 0) if latest_tx is not None else 0
        wallet = {
            "customer_discord_id": str(customer_discord_id),
            "balance": balance,
            "principal_balance": balance,
            "bonus_balance": 0,
            "refund_offset_balance": 0,
            "updated_at": latest_tx["created_at"] if latest_tx is not None else None,
        }

    customer_id = str(wallet.get("customer_discord_id") or "")
    display_names = fetch_customer_display_names([customer_id])
    wallet["customer_display_name"] = (
        display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
    )
    _decorate_wallet(wallet)

    transactions = []
    for row in tx_rows:
        tx = dict(row)
        amount = int(tx.get("amount") or 0)
        tx["amount_text"] = (
            f"+{format_t_amount(amount)}"
            if amount > 0
            else f"-{format_t_amount(abs(amount))}"
        )
        tx["balance_before_text"] = format_t_amount(tx.get("balance_before"))
        tx["balance_after_text"] = format_t_amount(tx.get("balance_after"))
        tx["type_label"] = wallet_type_label(tx.get("type"))
        tx["created_at_text"] = format_wallet_datetime(tx.get("created_at"))
        transactions.append(tx)

    return wallet, transactions


def fetch_wallet_refunds(customer_discord_id: str) -> list[dict]:
    refunds = list_customer_wallet_refunds(
        customer_discord_id,
        limit=20,
        db_file=bot_db_path(),
    )
    for refund in refunds:
        refund["amount_text"] = format_t_amount(refund.get("amount"))
        refund["wallet_debit_text"] = format_t_amount(refund.get("wallet_debit_amount"))
        refund["bonus_offset_text"] = format_t_amount(refund.get("bonus_offset_applied"))
        refund["bonus_revoked_text"] = format_t_amount(refund.get("bonus_revoked_amount"))
        refund["created_at_text"] = format_wallet_datetime(refund.get("created_at"))
        refund["completed_at_text"] = format_wallet_datetime(refund.get("completed_at"))
    return refunds


def _admin_display_name(user: dict) -> str:
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "管理員"
    )


def _redirect_detail(customer_id: str, key: str, message: object) -> RedirectResponse:
    return RedirectResponse(
        f"/admin/wallets/{customer_id}?{key}={quote(str(message), safe='')}",
        status_code=303,
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_wallets(
    request: Request,
    q: str | None = Query(default=None, description="搜尋 Discord ID、訂單、備註、操作人"),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    wallets = fetch_wallets(q)
    total_balance = sum(int(w.get("balance") or 0) for w in wallets)

    return templates.TemplateResponse(
        request=request,
        name="admin_wallets.html",
        context={
            "title": "顧客錢包",
            "user": user,
            "wallets": wallets,
            "q": q or "",
            "total_balance": total_balance,
            "total_balance_text": format_t_amount(total_balance),
            "wallet_count": len(wallets),
            "format_t_amount": format_t_amount,
        },
    )


@router.get("/{customer_discord_id}", response_class=HTMLResponse)
async def admin_wallet_detail(
    request: Request,
    customer_discord_id: str,
    limit: int = Query(default=100, ge=1, le=300),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    wallet, transactions = fetch_wallet_detail(
        customer_discord_id,
        limit=limit,
    )
    refunds = fetch_wallet_refunds(customer_discord_id)

    return templates.TemplateResponse(
        request=request,
        name="admin_wallet_detail.html",
        context={
            "title": "錢包流水",
            "user": user,
            "wallet": wallet,
            "transactions": transactions,
            "refunds": refunds,
            "limit": limit,
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@router.post("/{customer_discord_id}/refund")
async def admin_wallet_refund(
    request: Request,
    customer_discord_id: str,
    amount: int = Form(...),
    note: str = Form(default=""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    try:
        refund = create_wallet_refund_request(
            customer_discord_id=customer_discord_id,
            amount=int(amount),
            requested_by_discord_id=str(user.get("id") or ""),
            requested_by_display_name=_admin_display_name(user),
            note=note,
            db_file=bot_db_path(),
        )
    except ValueError as exc:
        return _redirect_detail(customer_discord_id, "error", exc)

    return _redirect_detail(
        customer_discord_id,
        "ok",
        f"退款 #{refund['id']} 已送出，Bot 將同步處理錢包與 VIP。",
    )
