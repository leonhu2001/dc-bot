
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



def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (str(table_name),),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return False

    return any(str(row["name"]) == str(column_name) for row in rows)


def _date_expr_for_table(
    conn: sqlite3.Connection,
    table_name: str,
    alias: str,
    candidates: list[str],
) -> str | None:
    parts = []

    for column_name in candidates:
        if _has_column(conn, table_name, column_name):
            parts.append(f"NULLIF({alias}.{column_name}, '')")

    if not parts:
        return None

    return "COALESCE(" + ", ".join(parts) + ")"


def _fetch_recent_profile_stats() -> dict[str, dict]:
    _ensure_tables()

    stats: dict[str, dict] = {}

    conn = _connect()
    try:
        if _has_table(conn, "web_orders") and _has_table(conn, "order_assignments"):
            completed_date_expr = _date_expr_for_table(
                conn,
                "web_orders",
                "wo",
                ["closed_at", "updated_at", "created_at"],
            )

            if completed_date_expr:
                rows = conn.execute(
                    f"""
                    SELECT
                        oa.worker_discord_id AS staff_discord_id,
                        COUNT(DISTINCT wo.id) AS recent_completed_count
                    FROM order_assignments oa
                    JOIN web_orders wo ON wo.id = oa.order_id
                    WHERE wo.status = 'closed'
                      AND COALESCE(oa.is_active, 1) = 1
                      AND datetime({completed_date_expr}) >= datetime('now', '-30 days')
                    GROUP BY oa.worker_discord_id
                    """
                ).fetchall()

                for row in rows:
                    staff_id = str(row["staff_discord_id"])
                    stats.setdefault(staff_id, {})
                    stats[staff_id]["recent_completed_count"] = int(row["recent_completed_count"] or 0)

        if _has_table(conn, "order_reviews") and _has_column(conn, "order_reviews", "created_at"):
            rows = conn.execute(
                """
                SELECT
                    staff_discord_id,
                    COUNT(*) AS recent_review_count
                FROM order_reviews
                WHERE COALESCE(is_public, 1) = 1
                  AND COALESCE(is_hidden, 0) = 0
                  AND datetime(NULLIF(created_at, '')) >= datetime('now', '-30 days')
                GROUP BY staff_discord_id
                """
            ).fetchall()

            for row in rows:
                staff_id = str(row["staff_discord_id"])
                stats.setdefault(staff_id, {})
                stats[staff_id]["recent_review_count"] = int(row["recent_review_count"] or 0)

            rows = conn.execute(
                """
                SELECT
                    staff_discord_id,
                    MAX(created_at) AS latest_review_at
                FROM order_reviews
                WHERE COALESCE(is_public, 1) = 1
                  AND COALESCE(is_hidden, 0) = 0
                GROUP BY staff_discord_id
                """
            ).fetchall()

            for row in rows:
                staff_id = str(row["staff_discord_id"])
                stats.setdefault(staff_id, {})
                stats[staff_id]["latest_review_at"] = str(row["latest_review_at"] or "").strip()

        return stats
    finally:
        conn.close()


def _date_text(value: str | None, empty_text: str = "無") -> str:
    text = str(value or "").strip()
    if not text:
        return empty_text
    return text[:10]

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



def _staff_profile_sync_command(staff_discord_id: str) -> str:
    staff_id = str(staff_discord_id or "").strip()
    return f"/refresh_staff_profile_panel member:<@{staff_id}>"


def _panel_status_html(row: sqlite3.Row) -> str:
    staff_id = str(row["staff_discord_id"] or "").strip()
    thread_id = str(row["forum_thread_id"] or "").strip()
    message_id = str(row["panel_message_id"] or "").strip()

    has_panel = bool(thread_id and message_id)
    badge_class = "ok" if has_panel else "off"
    badge_text = "Panel 已建立" if has_panel else "Panel 未建立"

    command = _esc(_staff_profile_sync_command(staff_id))

    if has_panel:
        location_text = f"Thread {thread_id}<br>Message {message_id}"
    else:
        location_text = "尚未記錄 Discord panel 位置"

    return f"""
        <div class="panel-box">
            <span class="badge {badge_class}">{badge_text}</span>
            <div class="panel-location">{_esc(location_text)}</div>
            <div class="sync-label">同步指令</div>
            <code>{command}</code>
        </div>
    """

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
    recent_stats = _fetch_recent_profile_stats()

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
        profile_recent_stats = recent_stats.get(str(row["staff_discord_id"]), {})
        recent_completed_count = int(profile_recent_stats.get("recent_completed_count") or 0)
        recent_review_count = int(profile_recent_stats.get("recent_review_count") or 0)
        latest_review_at = _esc(_date_text(profile_recent_stats.get("latest_review_at")))
        link = _discord_link(row)
        link_html = f'<a href="{_esc(link)}" target="_blank">打開</a>' if link else "尚未記錄"
        panel_status_html = _panel_status_html(row)

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
                評價 {avg_rating:.1f} / 5（{review_count}）<br>
                <span class="muted">近 30 天完成 {recent_completed_count}</span><br>
                <span class="muted">近 30 天評價 {recent_review_count}</span><br>
                <span class="muted">最近評價 {latest_review_at}</span>
            </td>
            <td><span class="badge {'ok' if is_public else 'off'}">{public_badge}</span></td>
            <td>
                <div>{link_html}</div>
                {panel_status_html}
            </td>
            <td class="bio">{bio}</td>
            <td>{updated_at}</td>
            <td class="actions">
                <a class="edit-link" href="/admin/staff_profiles/edit/{staff_id}">編輯</a>
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
        .actions {{ display: flex; flex-direction: column; gap: 8px; min-width: 88px; }}
        .edit-link {{
            display: inline-block;
            background: #334155;
            color: #e5e7eb;
            text-decoration: none;
            border-radius: 8px;
            padding: 7px 10px;
            text-align: center;
        }}
        .edit-link:hover {{ background: #475569; }}
        .panel-box {{
            margin-top: 8px;
            padding: 8px;
            border: 1px solid #334155;
            border-radius: 10px;
            background: #020617;
            min-width: 210px;
        }}
        .panel-location {{
            color: #94a3b8;
            font-size: 11px;
            margin-top: 6px;
            line-height: 1.4;
        }}
        .sync-label {{
            color: #cbd5e1;
            font-size: 12px;
            font-weight: 700;
            margin-top: 8px;
        }}
        code {{
            display: block;
            white-space: pre-wrap;
            word-break: break-all;
            margin-top: 4px;
            padding: 6px;
            border-radius: 8px;
            background: #111827;
            color: #fde68a;
            font-size: 12px;
        }}
        .empty {{ text-align: center; color: #94a3b8; padding: 32px; }}
    </style>
</head>
<body>
    <h1>成員個人牆後台</h1>
    <div class="sub">只管理個人牆顯示狀態，不影響訂單、接單、分潤。數據欄含總量與近 30 天資料。後台改資料後，可用同步指令更新 Discord panel。</div>

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



def _fetch_profile(staff_discord_id: str) -> sqlite3.Row | None:
    _ensure_tables()

    conn = _connect()
    try:
        return conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
            LIMIT 1
            """,
            (str(staff_discord_id),),
        ).fetchone()
    finally:
        conn.close()


def _profile_edit_page_html(row: sqlite3.Row) -> str:
    staff_id = _esc(row["staff_discord_id"])
    display_name = _esc(row["display_name"] or "")
    profile_type = _esc(row["profile_type"] or "")
    role_title = _esc(row["role_title"] or "")
    main_games = _esc(row["main_games"] or "")
    service_tags = _esc(row["service_tags"] or "")
    bio = _esc(row["bio"] or "")
    card_image_url = _esc(row["card_image_url"] or "")
    updated_at = _esc(row["updated_at"] or "")

    preview = (
        f'<img src="{card_image_url}" alt="名片預覽">'
        if card_image_url
        else '<div class="no-image">尚未設定名片圖片 URL</div>'
    )

    return f"""
<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <title>編輯成員個人牆</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 24px;
            background: #0f172a;
            color: #e5e7eb;
        }}
        .wrap {{ max-width: 920px; }}
        h1 {{ margin-bottom: 4px; }}
        .sub {{ color: #94a3b8; margin-bottom: 20px; }}
        .card {{
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 14px;
            padding: 18px;
        }}
        label {{
            display: block;
            margin: 14px 0 6px;
            color: #cbd5e1;
            font-weight: 700;
        }}
        input, textarea {{
            width: 100%;
            box-sizing: border-box;
            border: 1px solid #334155;
            border-radius: 10px;
            background: #020617;
            color: #e5e7eb;
            padding: 10px 12px;
            font-size: 14px;
        }}
        textarea {{ min-height: 150px; resize: vertical; }}
        .row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }}
        .actions {{
            display: flex;
            gap: 10px;
            align-items: center;
            margin-top: 18px;
        }}
        button {{
            background: #2563eb;
            color: white;
            border: 0;
            border-radius: 10px;
            padding: 10px 14px;
            cursor: pointer;
            font-weight: 700;
        }}
        button:hover {{ background: #1d4ed8; }}
        a {{
            color: #93c5fd;
            text-decoration: none;
        }}
        .muted {{ color: #94a3b8; font-size: 13px; }}
        .preview {{
            margin-top: 14px;
            background: #020617;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 12px;
        }}
        .preview img {{
            max-width: 100%;
            border-radius: 10px;
            display: block;
        }}
        .no-image {{ color: #94a3b8; padding: 24px; text-align: center; }}
    </style>
</head>
<body>
    <div class="wrap">
        <h1>編輯成員個人牆</h1>
        <div class="sub">
            成員 ID：{staff_id}｜最後更新：{updated_at}<br>
            這裡只修改個人牆資料，不影響訂單、接單、分潤。儲存後請回列表查看同步指令，或到 Discord 使用 /refresh_staff_profile_panel。
        </div>

        <form class="card" method="post" action="/admin/staff_profiles/edit/{staff_id}">
            <div class="row">
                <div>
                    <label>顯示名稱</label>
                    <input name="display_name" value="{display_name}" maxlength="80">
                </div>
                <div>
                    <label>類型</label>
                    <input name="profile_type" value="{profile_type}" maxlength="40" placeholder="打手 / 陪玩 / 主播">
                </div>
            </div>

            <div class="row">
                <div>
                    <label>階級 / 職位</label>
                    <input name="role_title" value="{role_title}" maxlength="80">
                </div>
                <div>
                    <label>主要遊戲</label>
                    <input name="main_games" value="{main_games}" maxlength="120">
                </div>
            </div>

            <label>服務項目</label>
            <input name="service_tags" value="{service_tags}" maxlength="200" placeholder="護航 / 技術陪 / 代做">

            <label>個人特色</label>
            <textarea name="bio" maxlength="1200">{bio}</textarea>

            <label>名片圖片 URL</label>
            <input name="card_image_url" value="{card_image_url}" maxlength="1000" placeholder="https://...">

            <div class="preview">
                <div class="muted">目前名片圖片預覽</div>
                {preview}
            </div>

            <div class="actions">
                <button type="submit">儲存變更</button>
                <a href="/admin/staff_profiles/">返回列表</a>
            </div>
        </form>
    </div>
</body>
</html>
"""


@router.get("/edit/{staff_discord_id}", response_class=HTMLResponse)
async def edit_staff_profile_page(request: Request, staff_discord_id: str):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    row = _fetch_profile(staff_discord_id)

    if row is None:
        return HTMLResponse(
            "<h1>找不到成員個人牆</h1><p><a href='/admin/staff_profiles/'>返回列表</a></p>",
            status_code=404,
        )

    return HTMLResponse(_profile_edit_page_html(row))


@router.post("/edit/{staff_discord_id}")
async def update_staff_profile_page(
    request: Request,
    staff_discord_id: str,
    display_name: str = Form(""),
    profile_type: str = Form(""),
    role_title: str = Form(""),
    main_games: str = Form(""),
    service_tags: str = Form(""),
    bio: str = Form(""),
    card_image_url: str = Form(""),
):
    if not _is_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    _ensure_tables()

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT staff_discord_id FROM staff_profiles WHERE staff_discord_id = ?",
            (str(staff_discord_id),),
        ).fetchone()

        if row is None:
            return RedirectResponse(url="/admin/staff_profiles/", status_code=303)

        conn.execute(
            """
            UPDATE staff_profiles
            SET display_name = ?,
                profile_type = ?,
                role_title = ?,
                main_games = ?,
                service_tags = ?,
                bio = ?,
                card_image_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE staff_discord_id = ?
            """,
            (
                str(display_name or "").strip(),
                str(profile_type or "").strip(),
                str(role_title or "").strip(),
                str(main_games or "").strip(),
                str(service_tags or "").strip(),
                str(bio or "").strip(),
                str(card_image_url or "").strip(),
                str(staff_discord_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/staff_profiles/", status_code=303)


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
