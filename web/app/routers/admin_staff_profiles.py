
from __future__ import annotations

import html
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter(prefix="/admin/staff_profiles", tags=["admin-staff-profiles"])


def _db_path() -> Path:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./web_dashboard.db")
    if database_url.startswith("sqlite:///"):
        raw = database_url.replace("sqlite:///", "", 1)
        path = Path(raw)
        if not path.is_absolute():
            return Path.cwd() / path
        return path

    root = Path(__file__).resolve().parents[3]
    return root / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _is_admin(request: Request) -> bool:
    user = request.session.get("user") or {}
    if not user:
        return False

    if user.get("is_admin") or user.get("is_owner") or user.get("admin"):
        return True

    role_ids = set()

    for key in ("role_ids", "roles", "discord_role_ids"):
        value = user.get(key)
        if isinstance(value, list):
            role_ids.update(str(v) for v in value)
        elif isinstance(value, str):
            role_ids.update(part.strip() for part in value.replace("[", "").replace("]", "").replace('"', "").split(",") if part.strip())

    # 客服 / 管理常用角色；沒有角色資料時不放行
    allowed_role_ids = {
        "1482084782031638548",  # 魔丸客服
    }

    return bool(role_ids & allowed_role_ids)


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _ensure_tables() -> None:
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_profiles (
                staff_discord_id TEXT PRIMARY KEY,
                display_name TEXT,
                profile_type TEXT,
                role_title TEXT,
                main_games TEXT,
                service_tags TEXT,
                bio TEXT,
                card_image_url TEXT,
                forum_thread_id TEXT,
                forum_channel_id TEXT,
                panel_message_id TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                source TEXT NOT NULL DEFAULT 'profile',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_favorites_unique
            ON staff_favorites(customer_discord_id, staff_discord_id)
        """)

        conn.commit()
    finally:
        conn.close()


def _fetch_profiles() -> list[sqlite3.Row]:
    _ensure_tables()

    conn = _connect()
    try:
        return conn.execute("""
            SELECT
                p.*,
                COALESCE(f.favorite_count, 0) AS favorite_count,
                COALESCE(r.review_count, 0) AS review_count,
                COALESCE(r.average_rating, 0) AS average_rating,
                COALESCE(o.completed_count, 0) AS completed_count
            FROM staff_profiles p
            LEFT JOIN (
                SELECT staff_discord_id, COUNT(*) AS favorite_count
                FROM staff_favorites
                GROUP BY staff_discord_id
            ) f ON f.staff_discord_id = p.staff_discord_id
            LEFT JOIN (
                SELECT
                    staff_discord_id,
                    COUNT(*) AS review_count,
                    AVG(rating) AS average_rating
                FROM order_reviews
                WHERE is_public = 1
                  AND is_hidden = 0
                GROUP BY staff_discord_id
            ) r ON r.staff_discord_id = p.staff_discord_id
            LEFT JOIN (
                SELECT
                    oa.worker_discord_id AS staff_discord_id,
                    COUNT(DISTINCT wo.id) AS completed_count
                FROM order_assignments oa
                JOIN web_orders wo ON wo.id = oa.order_id
                WHERE wo.status = 'closed'
                  AND oa.is_active = 1
                GROUP BY oa.worker_discord_id
            ) o ON o.staff_discord_id = p.staff_discord_id
            ORDER BY p.updated_at DESC, p.created_at DESC
        """).fetchall()
    finally:
        conn.close()


def _discord_link(row: sqlite3.Row) -> str:
    thread_id = row["forum_thread_id"]
    message_id = row["panel_message_id"]

    if thread_id and message_id:
        return f"https://discord.com/channels/@me/{thread_id}/{message_id}"

    if thread_id:
        return f"https://discord.com/channels/@me/{thread_id}"

    return ""


@router.get("/", response_class=HTMLResponse)
async def staff_profiles_index(request: Request):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    profiles = _fetch_profiles()

    rows_html = []

    for row in profiles:
        staff_id = _esc(row["staff_discord_id"])
        display_name = _esc(row["display_name"] or row["staff_discord_id"])
        profile_type = _esc(row["profile_type"] or "成員")
        role_title = _esc(row["role_title"] or "")
        games = _esc(row["main_games"] or "")
        services = _esc(row["service_tags"] or "")
        bio = _esc(row["bio"] or "")
        updated_at = _esc(row["updated_at"] or "")
        is_public = int(row["is_public"] or 0) == 1
        public_badge = "公開" if is_public else "隱藏"
        toggle_label = "設為隱藏" if is_public else "設為公開"
        avg_rating = float(row["average_rating"] or 0)
        review_count = int(row["review_count"] or 0)
        favorite_count = int(row["favorite_count"] or 0)
        completed_count = int(row["completed_count"] or 0)
        link = _discord_link(row)
        link_html = f'<a href="{_esc(link)}" target="_blank">打開</a>' if link else "尚未記錄"

        rows_html.append(f"""
        <tr>
            <td>
                <div class="name">{display_name}</div>
                <div class="muted">{staff_id}</div>
            </td>
            <td>{profile_type}</td>
            <td>{role_title}</td>
            <td>{games}</td>
            <td>{services}</td>
            <td>
                收藏 {favorite_count}<br>
                完成 {completed_count}<br>
                評價 {avg_rating:.1f} / 5（{review_count}）
            </td>
            <td><span class="badge {'ok' if is_public else 'off'}">{public_badge}</span></td>
            <td>{link_html}</td>
            <td class="bio">{bio}</td>
            <td>{updated_at}</td>
            <td>
                <form method="post" action="/admin/staff_profiles/toggle_public">
                    <input type="hidden" name="staff_discord_id" value="{staff_id}">
                    <button type="submit">{toggle_label}</button>
                </form>
            </td>
        </tr>
        """)

    body = "\n".join(rows_html) or """
        <tr>
            <td colspan="11" class="empty">目前還沒有成員個人牆。</td>
        </tr>
    """

    html_text = f"""
<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <title>成員個人牆後台</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 24px;
            background: #0f172a;
            color: #e5e7eb;
        }}
        h1 {{ margin-bottom: 4px; }}
        .sub {{ color: #94a3b8; margin-bottom: 20px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #111827;
            border-radius: 12px;
            overflow: hidden;
        }}
        th, td {{
            padding: 10px 12px;
            border-bottom: 1px solid #1f2937;
            vertical-align: top;
            font-size: 14px;
        }}
        th {{
            text-align: left;
            background: #1e293b;
            color: #cbd5e1;
            white-space: nowrap;
        }}
        .name {{ font-weight: 700; }}
        .muted {{ color: #94a3b8; font-size: 12px; margin-top: 3px; }}
        .bio {{ max-width: 260px; white-space: pre-wrap; color: #cbd5e1; }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }}
        .badge.ok {{ background: #064e3b; color: #a7f3d0; }}
        .badge.off {{ background: #3f1d1d; color: #fecaca; }}
        button {{
            background: #2563eb;
            color: white;
            border: 0;
            border-radius: 8px;
            padding: 7px 10px;
            cursor: pointer;
        }}
        button:hover {{ background: #1d4ed8; }}
        a {{ color: #93c5fd; }}
        .empty {{ text-align: center; color: #94a3b8; padding: 32px; }}
    </style>
</head>
<body>
    <h1>成員個人牆後台</h1>
    <div class="sub">只管理個人牆顯示狀態，不影響訂單、接單、分潤。</div>

    <table>
        <thead>
            <tr>
                <th>成員</th>
                <th>類型</th>
                <th>職位</th>
                <th>遊戲</th>
                <th>服務</th>
                <th>數據</th>
                <th>狀態</th>
                <th>個人牆</th>
                <th>介紹</th>
                <th>更新時間</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
            {body}
        </tbody>
    </table>
</body>
</html>
"""
    return HTMLResponse(html_text)


@router.post("/toggle_public")
async def toggle_staff_profile_public(
    request: Request,
    staff_discord_id: str = Form(...),
):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    _ensure_tables()

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT is_public FROM staff_profiles WHERE staff_discord_id = ?",
            (str(staff_discord_id),),
        ).fetchone()

        if row is not None:
            next_value = 0 if int(row["is_public"] or 0) == 1 else 1
            conn.execute(
                """
                UPDATE staff_profiles
                SET is_public = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE staff_discord_id = ?
                """,
                (next_value, str(staff_discord_id)),
            )
            conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/staff_profiles/", status_code=303)
