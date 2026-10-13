from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
import sqlite3

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.wallet_refunds import (
    create_wallet_refund_request,
    get_wallet_refund_preview,
)
from services.wallet_service import ensure_wallet_tables as ensure_shared_wallet_tables


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
    if not clean_ids or not web_dashboard_db_path().exists():
        return {}
    try:
        with sqlite3.connect(web_dashboard_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cols = _table_columns(conn, "web_orders")
            if "customer_discord_id" not in cols:
                return {}
            name_candidates = [
                "customer_display_name", "customer_name",
                "customer_nickname", "customer_username",
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
                  AND {name_col} IS NOT NULL AND TRIM({name_col}) != ''
                GROUP BY customer_discord_id
                """,
                clean_ids,
            ).fetchall()
            return {
                str(row["customer_discord_id"]): str(row["display_name"] or "").strip()
                for row in rows
                if str(row["customer_discord_id"] or "").strip()
                and str(row["display_name"] or "").strip()
            }
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
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        text = text.replace("T", " ")
        if "+" in text:
            text = text.split("+", 1)[0]
        return text[:16].replace("-", "/") if len(text) >= 16 else text


def wallet_type_label(tx_type: str | None) -> str:
    mapping = {
        "topup": "儲值本金",
        "topup_bonus": "儲值返利",
        "topup_bonus_reversal": "取消儲值返利",
        "topup_refund": "儲值退款",
        "payment": "訂單扣款",
        "tip_payment": "雞腿扣款",
        "refund": "退款",
        "adjustment": "修正",
        "manual_adjustment": "手動調整",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def ensure_wallet_tables() -> None:
    ensure_shared_wallet_tables(bot_db_path())


def fetch_wallets(keyword: str | None = None) -> list[dict]:
    ensure_wallet_tables()
    q = str(keyword or "").strip()
    sql = """
        SELECT w.customer_discord_id, w.balance, w.updated_at,
            (SELECT COUNT(*) FROM wallet_transactions t
             WHERE t.customer_discord_id=w.customer_discord_id) AS transaction_count,
            (SELECT t.note FROM wallet_transactions t
             WHERE t.customer_discord_id=w.customer_discord_id
               AND t.note IS NOT NULL AND TRIM(t.note)!=''
             ORDER BY t.id DESC LIMIT 1) AS last_note,
            (SELECT t.operator_display_name FROM wallet_transactions t
             WHERE t.customer_discord_id=w.customer_discord_id
               AND t.operator_display_name IS NOT NULL
               AND TRIM(t.operator_display_name)!=''
             ORDER BY t.id DESC LIMIT 1) AS last_operator
        FROM customer_wallets w
    """
    params: list[str] = []
    if q:
        like = f"%{q}%"
        sql += """
            WHERE w.customer_discord_id LIKE ? OR EXISTS (
                SELECT 1 FROM wallet_transactions t
                WHERE t.customer_discord_id=w.customer_discord_id
                  AND (t.note LIKE ? OR t.order_no LIKE ? OR t.operator_display_name LIKE ?)
            )
        """
        params.extend([like, like, like, like])
    sql += " ORDER BY w.updated_at DESC, CAST(w.balance AS INTEGER) DESC"

    with sqlite3.connect(bot_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    display_names = fetch_customer_display_names([str(row["customer_discord_id"]) for row in rows])
    result = []
    for row in rows:
        data = dict(row)
        customer_id = str(data.get("customer_discord_id") or "")
        data["customer_display_name"] = display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
        data["balance_text"] = format_t_amount(data.get("balance"))
        data["updated_at_text"] = format_wallet_datetime(data.get("updated_at"))
        result.append(data)
    return result


def fetch_wallet_detail(customer_discord_id: str, limit: int = 100) -> tuple[dict, list[dict]]:
    ensure_wallet_tables()
    safe_limit = max(1, min(int(limit or 100), 300))
    with sqlite3.connect(bot_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        wallet_row = conn.execute(
            "SELECT customer_discord_id,balance,updated_at FROM customer_wallets WHERE customer_discord_id=?",
            (str(customer_discord_id),),
        ).fetchone()
        tx_rows = conn.execute(
            """
            SELECT id,customer_discord_id,amount,balance_before,balance_after,type,
                   order_channel_id,order_no,operator_discord_id,
                   operator_display_name,note,created_at
            FROM wallet_transactions
            WHERE customer_discord_id=? ORDER BY id DESC LIMIT ?
            """,
            (str(customer_discord_id), safe_limit),
        ).fetchall()

    if wallet_row is not None:
        wallet = dict(wallet_row)
    else:
        latest_tx = tx_rows[0] if tx_rows else None
        wallet = {
            "customer_discord_id": str(customer_discord_id),
            "balance": int(latest_tx["balance_after"] or 0) if latest_tx else 0,
            "updated_at": latest_tx["created_at"] if latest_tx else None,
        }
    customer_id = str(wallet.get("customer_discord_id") or "")
    display_names = fetch_customer_display_names([customer_id])
    wallet["customer_display_name"] = display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
    wallet["balance_text"] = format_t_amount(wallet.get("balance"))
    wallet["updated_at_text"] = format_wallet_datetime(wallet.get("updated_at"))

    transactions = []
    for raw in tx_rows:
        tx = dict(raw)
        amount = int(tx.get("amount") or 0)
        tx["amount_text"] = f"+{format_t_amount(amount)}" if amount > 0 else f"-{format_t_amount(abs(amount))}"
        tx["balance_before_text"] = format_t_amount(tx.get("balance_before"))
        tx["balance_after_text"] = format_t_amount(tx.get("balance_after"))
        tx["type_label"] = wallet_type_label(tx.get("type"))
        tx["created_at_text"] = format_wallet_datetime(tx.get("created_at"))
        transactions.append(tx)
    return wallet, transactions


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_wallets(request: Request, q: str | None = Query(default=None)):
    if not _mwfinal_wallet_admin_user(request):
        return _mwfinal_wallet_redirect(url="/admin", status_code=303)
    wallets = fetch_wallets(q)
    total_balance = sum(int(w.get("balance") or 0) for w in wallets)
    return templates.TemplateResponse(
        request,
        "admin_wallets.html",
        {
            "title": "顧客錢包", "user": request.session.get("user"),
            "wallets": wallets, "q": q or "", "total_balance": total_balance,
            "total_balance_text": format_t_amount(total_balance),
            "wallet_count": len(wallets), "format_t_amount": format_t_amount,
        },
    )


@router.get("/{customer_discord_id}", response_class=HTMLResponse)
async def admin_wallet_detail(
    request: Request,
    customer_discord_id: str,
    limit: int = Query(default=100, ge=1, le=300),
):
    if not _mwfinal_wallet_admin_user(request):
        return _mwfinal_wallet_redirect(url="/admin", status_code=303)
    wallet, transactions = fetch_wallet_detail(customer_discord_id, limit=limit)
    preview = get_wallet_refund_preview(
        customer_discord_id,
        bot_db=bot_db_path(),
        web_db=web_dashboard_db_path(),
    )
    preview["refundable_principal_text"] = format_t_amount(preview.get("refundable_principal"))
    preview["nonrefundable_credit_text"] = format_t_amount(preview.get("nonrefundable_credit"))
    preview["topup_bonus_to_cancel_text"] = format_t_amount(preview.get("topup_bonus_to_cancel"))
    return templates.TemplateResponse(
        request,
        "admin_wallet_detail.html",
        {
            "title": "錢包流水", "user": request.session.get("user"),
            "wallet": wallet, "transactions": transactions, "limit": limit,
            "refund_preview": preview,
            "refund_ok": request.query_params.get("refund_ok", ""),
            "refund_error": request.query_params.get("refund_error", ""),
        },
    )


@router.post("/{customer_discord_id}/refund-principal")
async def admin_wallet_refund_principal(
    request: Request,
    customer_discord_id: str,
    reason: str = Form(default=""),
):
    admin = _mwfinal_wallet_admin_user(request)
    if not admin:
        return _mwfinal_wallet_redirect(url="/admin", status_code=303)
    user = request.session.get("user") or {}
    operator_id = user.get("id") or user.get("discord_id")
    operator_name = user.get("display_name") or user.get("global_name") or user.get("username")
    try:
        refund = create_wallet_refund_request(
            customer_id=customer_discord_id,
            requested_by_discord_id=operator_id,
            requested_by_display_name=operator_name,
            reason=reason,
            bot_db=bot_db_path(),
            web_db=web_dashboard_db_path(),
        )
        message = f"退款申請 {refund.get('refund_no')} 已送出，Bot 將自動完成錢包與 VIP 回滾。"
        query = urlencode({"refund_ok": message})
    except ValueError as exc:
        query = urlencode({"refund_error": str(exc)})
    return RedirectResponse(
        url=f"/admin/wallets/{customer_discord_id}?{query}",
        status_code=303,
    )


# MAWAN_FINAL_WALLET_ADMIN_GUARD_V1
from web.app.routers.admin_staff import _mw4b2_admin_user as _mwfinal_wallet_admin_user
from fastapi.responses import RedirectResponse as _mwfinal_wallet_redirect
