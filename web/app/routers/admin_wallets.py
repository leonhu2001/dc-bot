
from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


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
    """從 web_orders 補顧客顯示名稱，沒有資料就 fallback Discord ID。"""
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
                SELECT customer_discord_id, {name_col} AS display_name, MAX({order_col}) AS latest_id
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


def wallet_type_label(tx_type: str | None) -> str:
    mapping = {
        "topup": "儲值",
        "payment": "訂單扣款",
        "refund": "退款",
        "adjustment": "修正",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def ensure_wallet_tables() -> None:
    with sqlite3.connect(bot_db_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                order_channel_id TEXT,
                order_no TEXT,
                operator_discord_id TEXT,
                operator_display_name TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def fetch_wallets(keyword: str | None = None) -> list[dict]:
    ensure_wallet_tables()

    q = str(keyword or "").strip()

    sql = """
        SELECT
            w.customer_discord_id,
            w.balance,
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

    wallets = []
    customer_ids = [str(row["customer_discord_id"]) for row in rows]
    display_names = fetch_customer_display_names(customer_ids)

    for row in rows:
        data = dict(row)
        customer_id = str(data.get("customer_discord_id") or "")
        data["customer_display_name"] = display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
        data["balance_text"] = format_t_amount(data.get("balance"))
        wallets.append(data)

    return wallets


def fetch_wallet_detail(customer_discord_id: str, limit: int = 100) -> tuple[dict, list[dict]]:
    ensure_wallet_tables()

    safe_limit = max(1, min(int(limit or 100), 300))

    with sqlite3.connect(bot_db_path()) as conn:
        conn.row_factory = sqlite3.Row

        wallet_row = conn.execute(
            """
            SELECT customer_discord_id, balance, updated_at
            FROM customer_wallets
            WHERE customer_discord_id = ?
            """,
            (str(customer_discord_id),),
        ).fetchone()

        if wallet_row is None:
            raise HTTPException(status_code=404, detail="找不到此顧客錢包。")

        tx_rows = conn.execute(
            """
            SELECT
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_channel_id,
                order_no,
                operator_discord_id,
                operator_display_name,
                note,
                created_at
            FROM wallet_transactions
            WHERE customer_discord_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_discord_id), safe_limit),
        ).fetchall()

    wallet = dict(wallet_row)
    customer_id = str(wallet.get("customer_discord_id") or "")
    display_names = fetch_customer_display_names([customer_id])
    wallet["customer_display_name"] = display_names.get(customer_id) or f"老闆 {customer_id[-4:]}"
    wallet["balance_text"] = format_t_amount(wallet.get("balance"))

    transactions = []
    for row in tx_rows:
        tx = dict(row)
        amount = int(tx.get("amount") or 0)
        tx["amount_text"] = f"+{format_t_amount(amount)}" if amount > 0 else f"-{format_t_amount(abs(amount))}"
        tx["balance_before_text"] = format_t_amount(tx.get("balance_before"))
        tx["balance_after_text"] = format_t_amount(tx.get("balance_after"))
        tx["type_label"] = wallet_type_label(tx.get("type"))
        transactions.append(tx)

    return wallet, transactions


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_wallets(
    request: Request,
    q: str | None = Query(default=None, description="搜尋 Discord ID、訂單、備註、操作人"),
):
    wallets = fetch_wallets(q)
    total_balance = sum(int(w.get("balance") or 0) for w in wallets)

    return templates.TemplateResponse(
        request,
        "admin_wallets.html",
        {
            "title": "顧客錢包",
            "user": request.session.get("user"),
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
    wallet, transactions = fetch_wallet_detail(customer_discord_id, limit=limit)

    return templates.TemplateResponse(
        request,
        "admin_wallet_detail.html",
        {
            "title": "錢包流水",
            "user": request.session.get("user"),
            "wallet": wallet,
            "transactions": transactions,
            "limit": limit,
        },
    )
