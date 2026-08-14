from __future__ import annotations

import html
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter(prefix="/admin/reviews", tags=["admin-reviews"])


def _db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                customer_discord_id TEXT,
                rating INTEGER NOT NULL,
                comment TEXT,
                service_category TEXT,
                service_item TEXT,
                order_content TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_review_skips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT,
                staff_discord_id TEXT,
                skipped_all INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _require_admin(request: Request) -> dict | None:
    user = request.session.get("user")
    if not user:
        return None
    if not user.get("is_admin"):
        return None
    return user


def _esc(value) -> str:
    return html.escape(str(value or ""))


@router.get("/", response_class=HTMLResponse)
async def review_list(request: Request, staff_id: str | None = None, public: str | None = None):
    user = _require_admin(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    _ensure_tables()

    where = []
    params = []

    if staff_id:
        where.append("staff_discord_id = ?")
        params.append(str(staff_id))

    if public == "1":
        where.append("is_public = 1")
    elif public == "0":
        where.append("is_public = 0")

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM order_reviews
            {where_sql}
            ORDER BY id DESC
            LIMIT 300
            """,
            params,
        ).fetchall()

        skip_count = conn.execute("SELECT COUNT(*) AS c FROM order_review_skips").fetchone()["c"]
    finally:
        conn.close()

    table_rows = []
    for row in rows:
        stars = "⭐" * int(row["rating"] or 0)
        hidden_text = "已隱藏" if int(row["is_hidden"] or 0) else "顯示中"
        public_text = "公開" if int(row["is_public"] or 0) else "不公開"

        table_rows.append(
            "<tr>"
            f"<td>{row['id']}</td>"
            f"<td>WEB-{_esc(row['order_id'])}</td>"
            f"<td>{_esc(row['staff_display_name'])}<br><small>{_esc(row['staff_discord_id'])}</small></td>"
            f"<td>{_esc(row['customer_discord_id'])}</td>"
            f"<td>{stars}<br>{_esc(row['rating'])}/5</td>"
            f"<td>{_esc(row['service_category'])}<br>{_esc(row['service_item'])}</td>"
            f"<td style='max-width:360px;white-space:pre-wrap'>{_esc(row['comment'])}</td>"
            f"<td>{public_text}<br>{hidden_text}</td>"
            f"<td>{_esc(row['created_at'])}</td>"
            "<td>"
            f"<form method='post' action='/admin/reviews/{row['id']}/toggle-hidden'>"
            "<button type='submit'>切換隱藏</button>"
            "</form>"
            f"<form method='post' action='/admin/reviews/{row['id']}/toggle-public'>"
            "<button type='submit'>切換公開</button>"
            "</form>"
            "</td>"
            "</tr>"
        )

    html_body = f"""
    <!doctype html>
    <html lang="zh-Hant">
    <head>
      <meta charset="utf-8">
      <title>評價管理</title>
      <style>
        body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 24px; background:#0f172a; color:#e5e7eb; }}
        a {{ color:#93c5fd; }}
        table {{ width:100%; border-collapse:collapse; margin-top:16px; background:#111827; }}
        th, td {{ border:1px solid #374151; padding:8px; vertical-align:top; }}
        th {{ background:#1f2937; }}
        button {{ margin:2px 0; padding:4px 8px; }}
        input, select {{ padding:6px; }}
      </style>
    </head>
    <body>
      <h1>評價管理</h1>
      <p><a href="/admin">回管理後台</a></p>
      <p>目前顯示最近 300 筆評價；不留評價紀錄：{skip_count} 筆。</p>

      <form method="get" action="/admin/reviews/">
        <label>成員 Discord ID：</label>
        <input name="staff_id" value="{_esc(staff_id or '')}">
        <label>公開狀態：</label>
        <select name="public">
          <option value="" {"selected" if public not in {"0","1"} else ""}>全部</option>
          <option value="1" {"selected" if public == "1" else ""}>公開</option>
          <option value="0" {"selected" if public == "0" else ""}>不公開</option>
        </select>
        <button type="submit">篩選</button>
      </form>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>訂單</th>
            <th>成員</th>
            <th>顧客</th>
            <th>星等</th>
            <th>服務</th>
            <th>評語</th>
            <th>狀態</th>
            <th>時間</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {''.join(table_rows) if table_rows else '<tr><td colspan="10">目前沒有評價。</td></tr>'}
        </tbody>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(html_body)


@router.post("/{review_id}/toggle-hidden")
async def toggle_hidden(request: Request, review_id: int):
    user = _require_admin(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    _ensure_tables()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE order_reviews
            SET is_hidden = CASE WHEN COALESCE(is_hidden, 0) = 1 THEN 0 ELSE 1 END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (review_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/reviews/", status_code=303)


@router.post("/{review_id}/toggle-public")
async def toggle_public(request: Request, review_id: int):
    user = _require_admin(request)
    if user is None:
        return RedirectResponse(url="/no-access", status_code=303)

    _ensure_tables()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE order_reviews
            SET is_public = CASE WHEN COALESCE(is_public, 1) = 1 THEN 0 ELSE 1 END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (review_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/reviews/", status_code=303)
