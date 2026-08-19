from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import discord


# 個人牆指定下單：
# 真正建立票口的邏輯由 bot.py 注入，
# 避免 views.staff_profiles 直接 import bot.py 造成 circular import。
_STAFF_PROFILE_ORDER_TICKET_CREATOR = None


def configure_staff_profile_order_ticket_creator(creator) -> None:
    global _STAFF_PROFILE_ORDER_TICKET_CREATOR
    _STAFF_PROFILE_ORDER_TICKET_CREATOR = creator


async def _open_staff_profile_order_ticket(
    interaction: discord.Interaction,
    staff_id: int | str,
):
    creator = _STAFF_PROFILE_ORDER_TICKET_CREATOR

    if creator is None:
        await interaction.response.send_message(
            "指定下單功能尚未完成初始化，請通知客服。",
            ephemeral=True,
        )
        return

    try:
        await creator(
            interaction=interaction,
            staff_id=str(staff_id),
        )
    except ValueError as exc:
        if interaction.response.is_done():
            await interaction.followup.send(
                str(exc),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                str(exc),
                ephemeral=True,
            )
    except Exception as exc:
        print(
            "[staff-profile-order] "
            f"create ticket failed staff_id={staff_id}: "
            f"{type(exc).__name__}: {exc}"
        )

        message = (
            "建立指定下單票口失敗，"
            "請稍後再試或通知客服。"
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _web_db_path() -> Path:
    return _root_dir() / "web_dashboard.db"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_web_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_staff_profile_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS staff_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_discord_id TEXT NOT NULL UNIQUE,
                display_name TEXT,
                profile_type TEXT NOT NULL DEFAULT '打手',
                role_title TEXT,
                main_games TEXT,
                service_tags TEXT,
                bio TEXT,
                card_image_url TEXT,
                forum_thread_id TEXT,
                forum_channel_id TEXT,
                panel_message_id TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                sort_score INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_staff_profiles_public
                ON staff_profiles(is_public, sort_score);

            CREATE TABLE IF NOT EXISTS staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                source TEXT NOT NULL DEFAULT 'profile',
                created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_favorites_unique
                ON staff_favorites(customer_discord_id, staff_discord_id);

            CREATE INDEX IF NOT EXISTS idx_staff_favorites_customer
                ON staff_favorites(customer_discord_id);

            CREATE INDEX IF NOT EXISTS idx_staff_favorites_staff
                ON staff_favorites(staff_discord_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def get_staff_profile(staff_id: int | str) -> dict | None:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
            LIMIT 1
            """,
            (str(staff_id),),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def upsert_staff_profile(
    *,
    staff_id: int | str,
    display_name: str,
    profile_type: str,
    role_title: str,
    main_games: str,
    service_tags: str,
    bio: str,
    card_image_url: str | None,
    forum_thread_id: int | str | None,
    forum_channel_id: int | str | None,
    is_public: bool = True,
) -> dict:
    ensure_staff_profile_tables()
    now = _now_iso()
    conn = _connect()
    try:
        existing = conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
            LIMIT 1
            """,
            (str(staff_id),),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO staff_profiles (
                    staff_discord_id,
                    display_name,
                    profile_type,
                    role_title,
                    main_games,
                    service_tags,
                    bio,
                    card_image_url,
                    forum_thread_id,
                    forum_channel_id,
                    is_public,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(staff_id),
                    str(display_name or staff_id),
                    str(profile_type or "打手"),
                    str(role_title or ""),
                    str(main_games or ""),
                    str(service_tags or ""),
                    str(bio or ""),
                    str(card_image_url or ""),
                    str(forum_thread_id or ""),
                    str(forum_channel_id or ""),
                    1 if is_public else 0,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE staff_profiles
                SET display_name = ?,
                    profile_type = ?,
                    role_title = ?,
                    main_games = ?,
                    service_tags = ?,
                    bio = ?,
                    card_image_url = CASE WHEN ? != '' THEN ? ELSE card_image_url END,
                    forum_thread_id = ?,
                    forum_channel_id = ?,
                    is_public = ?,
                    updated_at = ?
                WHERE staff_discord_id = ?
                """,
                (
                    str(display_name or staff_id),
                    str(profile_type or "打手"),
                    str(role_title or ""),
                    str(main_games or ""),
                    str(service_tags or ""),
                    str(bio or ""),
                    str(card_image_url or ""),
                    str(card_image_url or ""),
                    str(forum_thread_id or ""),
                    str(forum_channel_id or ""),
                    1 if is_public else 0,
                    now,
                    str(staff_id),
                ),
            )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
            LIMIT 1
            """,
            (str(staff_id),),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def save_staff_profile_panel_message(
    *,
    staff_id: int | str,
    panel_message_id: int | str,
    forum_thread_id: int | str | None = None,
    forum_channel_id: int | str | None = None,
) -> None:
    ensure_staff_profile_tables()
    now = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE staff_profiles
            SET panel_message_id = ?,
                forum_thread_id = COALESCE(NULLIF(?, ''), forum_thread_id),
                forum_channel_id = COALESCE(NULLIF(?, ''), forum_channel_id),
                updated_at = ?
            WHERE staff_discord_id = ?
            """,
            (
                str(panel_message_id or ""),
                str(forum_thread_id or ""),
                str(forum_channel_id or ""),
                now,
                str(staff_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_staff_profile_panel_rows() -> list[dict]:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE COALESCE(is_public, 1) = 1
              AND COALESCE(panel_message_id, '') != ''
            ORDER BY sort_score DESC, updated_at DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_staff_favorite(
    *,
    customer_id: int | str,
    staff_id: int | str,
    staff_display_name: str | None = None,
    source: str = "profile",
) -> bool:
    ensure_staff_profile_tables()
    now = _now_iso()
    conn = _connect()
    try:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO staff_favorites (
                customer_discord_id,
                staff_discord_id,
                staff_display_name,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(customer_id),
                str(staff_id),
                str(staff_display_name or staff_id),
                str(source or "profile"),
                now,
            ),
        )
        conn.commit()
        return conn.total_changes > before
    finally:
        conn.close()


def remove_staff_favorite(*, customer_id: int | str, staff_id: int | str) -> bool:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        before = conn.total_changes
        conn.execute(
            """
            DELETE FROM staff_favorites
            WHERE customer_discord_id = ?
              AND staff_discord_id = ?
            """,
            (str(customer_id), str(staff_id)),
        )
        conn.commit()
        return conn.total_changes > before
    finally:
        conn.close()


def is_staff_favorited(*, customer_id: int | str, staff_id: int | str) -> bool:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM staff_favorites
            WHERE customer_discord_id = ?
              AND staff_discord_id = ?
            LIMIT 1
            """,
            (str(customer_id), str(staff_id)),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def toggle_staff_favorite(
    *,
    customer_id: int | str,
    staff_id: int | str,
    staff_display_name: str | None = None,
) -> tuple[bool, str]:
    if is_staff_favorited(customer_id=customer_id, staff_id=staff_id):
        removed = remove_staff_favorite(customer_id=customer_id, staff_id=staff_id)
        return False, "已取消收藏。" if removed else "已取消收藏。"

    add_staff_favorite(
        customer_id=customer_id,
        staff_id=staff_id,
        staff_display_name=staff_display_name,
        source="profile",
    )
    return True, "已加入收藏。"



def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return False

    return any(str(row["name"]) == str(column_name) for row in rows)


def _coalesce_datetime_expr(
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

def get_profile_stats(staff_id: int | str) -> dict:
    ensure_staff_profile_tables()
    staff_id_text = str(staff_id)

    conn = _connect()
    try:
        favorite_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM staff_favorites
            WHERE staff_discord_id = ?
            """,
            (staff_id_text,),
        ).fetchone()["c"]

        completed_orders = 0
        recent_completed_orders = 0

        if _has_table(conn, "web_orders") and _has_table(conn, "order_assignments"):
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT wo.id) AS c
                FROM web_orders wo
                JOIN order_assignments oa
                  ON oa.order_id = wo.id
                WHERE oa.worker_discord_id = ?
                  AND COALESCE(oa.is_active, 1) = 1
                  AND wo.status = 'closed'
                """,
                (staff_id_text,),
            ).fetchone()
            completed_orders = int(row["c"] or 0)

            completed_date_expr = _coalesce_datetime_expr(
                conn,
                "web_orders",
                "wo",
                ["closed_at", "updated_at", "created_at"],
            )

            if completed_date_expr:
                row = conn.execute(
                    f"""
                    SELECT COUNT(DISTINCT wo.id) AS c
                    FROM web_orders wo
                    JOIN order_assignments oa
                      ON oa.order_id = wo.id
                    WHERE oa.worker_discord_id = ?
                      AND COALESCE(oa.is_active, 1) = 1
                      AND wo.status = 'closed'
                      AND datetime({completed_date_expr}) >= datetime('now', '-30 days')
                    """,
                    (staff_id_text,),
                ).fetchone()
                recent_completed_orders = int(row["c"] or 0)

        review_count = 0
        recent_review_count = 0
        average_rating = None
        latest_review_at = None

        if _has_table(conn, "order_reviews"):
            has_created_at = _has_column(conn, "order_reviews", "created_at")

            select_latest = ", MAX(created_at) AS latest_review_at" if has_created_at else ""

            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c,
                       AVG(rating) AS avg_rating
                       {select_latest}
                FROM order_reviews
                WHERE staff_discord_id = ?
                  AND COALESCE(is_public, 1) = 1
                  AND COALESCE(is_hidden, 0) = 0
                """,
                (staff_id_text,),
            ).fetchone()

            review_count = int(row["c"] or 0)
            average_rating = row["avg_rating"]

            if has_created_at:
                latest_review_at = row["latest_review_at"]

                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM order_reviews
                    WHERE staff_discord_id = ?
                      AND COALESCE(is_public, 1) = 1
                      AND COALESCE(is_hidden, 0) = 0
                      AND datetime(NULLIF(created_at, '')) >= datetime('now', '-30 days')
                    """,
                    (staff_id_text,),
                ).fetchone()
                recent_review_count = int(row["c"] or 0)

        return {
            "favorite_count": int(favorite_count or 0),
            "completed_orders": int(completed_orders or 0),
            "recent_completed_orders": int(recent_completed_orders or 0),
            "review_count": int(review_count or 0),
            "recent_review_count": int(recent_review_count or 0),
            "average_rating": float(average_rating) if average_rating is not None else None,
            "latest_review_at": str(latest_review_at or "").strip() or None,
        }
    finally:
        conn.close()

def list_public_reviews(staff_id: int | str, limit: int = 5) -> list[dict]:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        if not _has_table(conn, "order_reviews"):
            return []

        rows = conn.execute(
            """
            SELECT *
            FROM order_reviews
            WHERE staff_discord_id = ?
              AND COALESCE(is_public, 1) = 1
              AND COALESCE(is_hidden, 0) = 0
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(staff_id), int(limit or 5)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _short_text(value: str | None, limit: int = 1024) -> str:
    text = str(value or "").strip()
    if not text:
        return "未填寫"
    return text[:limit]



def _date_text(value: str | None, empty_text: str = "尚無公開評價") -> str:
    text = str(value or "").strip()

    if not text:
        return empty_text

    return text[:10]

def build_staff_profile_embed(profile: dict) -> discord.Embed:
    stats = get_profile_stats(profile["staff_discord_id"])

    profile_type = str(profile.get("profile_type") or "打手")
    display_name = str(profile.get("display_name") or profile.get("staff_discord_id") or "成員")
    staff_id = str(profile.get("staff_discord_id") or "")

    embed = discord.Embed(
        title=f"{profile_type}｜{display_name}",
        color=discord.Color.from_rgb(147, 197, 253),
        timestamp=datetime.now(),
    )

    embed.add_field(
        name="基本名片",
        value=(
            f"成員：<@{staff_id}>\n"
            f"階級：{_short_text(profile.get('role_title'), 200)}\n"
            f"遊戲：{_short_text(profile.get('main_games'), 200)}\n"
            f"服務：{_short_text(profile.get('service_tags'), 200)}"
        ),
        inline=False,
    )

    embed.add_field(
        name="個人特色",
        value=_short_text(profile.get("bio"), 700),
        inline=False,
    )

    avg = stats["average_rating"]
    if avg is None:
        rating_text = "尚無公開評價"
    else:
        rating_text = f"{avg:.1f}（{stats['review_count']} 則）"

    embed.add_field(
        name="數據",
        value=(
            f"❤️ 收藏數：{stats['favorite_count']}\n"
            f"✅ 完成訂單：{stats['completed_orders']}\n"
            f"⭐ 平均評價：{rating_text}\n"
            f"📆 近 30 天完成：{stats['recent_completed_orders']}\n"
            f"📝 近 30 天評價：{stats['recent_review_count']}\n"
            f"🕒 最近評價：{_date_text(stats.get('latest_review_at'))}"
        ),
        inline=False,
    )

    card_image_url = str(profile.get("card_image_url") or "").strip()
    if card_image_url:
        embed.set_image(url=card_image_url)

    embed.set_footer(text="不顯示即時在線狀態；是否可接單以下單當下確認為準。")
    return embed


def build_reviews_embed(profile: dict, reviews: list[dict]) -> discord.Embed:
    display_name = str(profile.get("display_name") or profile.get("staff_discord_id") or "成員")
    stats = get_profile_stats(profile["staff_discord_id"])
    avg = stats["average_rating"]

    embed = discord.Embed(
        title=f"{display_name}｜評價紀錄",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )

    embed.description = (
        f"⭐ 平均：{avg:.1f} / 5\n"
        f"📝 公開評價：{stats['review_count']} 則\n"
        f"✅ 完成訂單：{stats['completed_orders']}\n"
        f"📆 近 30 天完成：{stats['recent_completed_orders']}\n"
        f"📝 近 30 天評價：{stats['recent_review_count']}\n"
        f"🕒 最近評價：{_date_text(stats.get('latest_review_at'))}"
        if avg is not None
        else (
            "⭐ 平均：尚無公開評價\n"
            f"📝 公開評價：{stats['review_count']} 則\n"
            f"✅ 完成訂單：{stats['completed_orders']}\n"
            f"📆 近 30 天完成：{stats['recent_completed_orders']}\n"
            f"📝 近 30 天評價：{stats['recent_review_count']}\n"
            f"🕒 最近評價：{_date_text(stats.get('latest_review_at'))}"
        )
    )

    if not reviews:
        embed.add_field(
            name="最近評價",
            value="目前還沒有公開評價。",
            inline=False,
        )
        return embed

    lines = []
    for index, review in enumerate(reviews, start=1):
        rating = int(review.get("rating") or 0)
        stars = "⭐" * max(1, min(5, rating))
        service = "｜".join(
            part
            for part in [
                str(review.get("service_category") or "").strip(),
                str(review.get("service_item") or "").strip(),
            ]
            if part
        ) or "未記錄服務"
        created_at = str(review.get("created_at") or "")[:10] or "未記錄日期"
        comment = str(review.get("comment") or "").strip() or "未填寫評語"
        lines.append(f"{index}. {stars}｜{service}｜{created_at}\n{comment}")

    embed.add_field(
        name="最近評價",
        value="\n\n".join(lines)[:3900],
        inline=False,
    )
    return embed


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type:
        return attachment.content_type.startswith("image/")

    lower = attachment.filename.lower()
    return lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


async def find_profile_card_image_url(channel) -> str | None:
    if channel is None:
        return None

    candidate_messages = []

    if isinstance(channel, discord.Thread):
        try:
            candidate_messages.append(await channel.fetch_message(channel.id))
        except Exception:
            pass

    try:
        async for message in channel.history(limit=30, oldest_first=True):
            candidate_messages.append(message)
    except Exception:
        pass

    seen = set()
    for message in candidate_messages:
        message_id = getattr(message, "id", None)
        if message_id in seen:
            continue
        seen.add(message_id)

        for attachment in getattr(message, "attachments", []) or []:
            if _is_image_attachment(attachment):
                return attachment.url

    return None



def count_public_reviews(staff_id: int | str) -> int:
    ensure_staff_profile_tables()
    conn = _connect()
    try:
        if not _has_table(conn, "order_reviews"):
            return 0

        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM order_reviews
            WHERE staff_discord_id = ?
              AND COALESCE(is_public, 1) = 1
              AND COALESCE(is_hidden, 0) = 0
            """,
            (str(staff_id),),
        ).fetchone()

        return int(row["c"] or 0) if row else 0
    finally:
        conn.close()


def list_public_reviews_page(
    staff_id: int | str,
    *,
    page: int = 0,
    page_size: int = 5,
) -> list[dict]:
    ensure_staff_profile_tables()
    safe_page = max(0, int(page or 0))
    safe_page_size = max(1, min(10, int(page_size or 5)))
    offset = safe_page * safe_page_size

    conn = _connect()
    try:
        if not _has_table(conn, "order_reviews"):
            return []

        rows = conn.execute(
            """
            SELECT *
            FROM order_reviews
            WHERE staff_discord_id = ?
              AND COALESCE(is_public, 1) = 1
              AND COALESCE(is_hidden, 0) = 0
            ORDER BY id DESC
            LIMIT ?
            OFFSET ?
            """,
            (str(staff_id), safe_page_size, offset),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def build_reviews_page_embed(
    profile: dict,
    reviews: list[dict],
    *,
    page: int,
    page_size: int,
    total_count: int,
) -> discord.Embed:
    display_name = str(profile.get("display_name") or profile.get("staff_discord_id") or "成員")
    stats = get_profile_stats(profile["staff_discord_id"])
    avg = stats["average_rating"]

    total_pages = max(1, (int(total_count or 0) + int(page_size or 5) - 1) // int(page_size or 5))
    current_page = min(max(0, int(page or 0)), total_pages - 1)

    embed = discord.Embed(
        title=f"{display_name}｜全部評價",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )

    if avg is not None:
        rating_line = f"⭐ 平均：{avg:.1f} / 5"
    else:
        rating_line = "⭐ 平均：尚無公開評價"

    embed.description = (
        f"{rating_line}\n"
        f"📝 公開評價：{int(total_count or 0)} 則\n"
        f"✅ 完成訂單：{stats['completed_orders']}\n"
        f"📄 頁數：{current_page + 1} / {total_pages}"
    )

    if not reviews:
        embed.add_field(
            name="評價",
            value="目前還沒有公開評價。",
            inline=False,
        )
        return embed

    for index, review in enumerate(reviews, start=current_page * int(page_size or 5) + 1):
        rating = int(review.get("rating") or 0)
        stars = "⭐" * max(1, min(5, rating))
        service = "｜".join(
            part
            for part in [
                str(review.get("service_category") or "").strip(),
                str(review.get("service_item") or "").strip(),
            ]
            if part
        ) or "未記錄服務"

        created_at = str(review.get("created_at") or "")[:10] or "未記錄日期"
        comment = str(review.get("comment") or "").strip() or "未填寫評語"

        if len(comment) > 450:
            comment = comment[:447] + "..."

        embed.add_field(
            name=f"{index}. {stars}｜{service}｜{created_at}",
            value=comment,
            inline=False,
        )

    embed.set_footer(text="只顯示公開且未被後台隱藏的評價。")
    return embed


class StaffProfileReviewsPageView(discord.ui.View):
    def __init__(self, staff_id: int | str, *, page: int = 0, page_size: int = 5):
        super().__init__(timeout=300)
        self.staff_id = str(staff_id)
        self.page = max(0, int(page or 0))
        self.page_size = max(1, min(10, int(page_size or 5)))

        prev_button = discord.ui.Button(
            label="上一頁",
            style=discord.ButtonStyle.secondary,
            custom_id=f"staff_profile_reviews_prev:{self.staff_id}",
            row=0,
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        next_button = discord.ui.Button(
            label="下一頁",
            style=discord.ButtonStyle.secondary,
            custom_id=f"staff_profile_reviews_next:{self.staff_id}",
            row=0,
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

        self._refresh_button_state()

    def _total_count(self) -> int:
        return count_public_reviews(self.staff_id)

    def _max_page(self) -> int:
        total = self._total_count()
        return max(0, (total + self.page_size - 1) // self.page_size - 1)

    def _refresh_button_state(self) -> None:
        max_page = self._max_page()

        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue

            if str(child.custom_id or "").startswith("staff_profile_reviews_prev:"):
                child.disabled = self.page <= 0
            elif str(child.custom_id or "").startswith("staff_profile_reviews_next:"):
                child.disabled = self.page >= max_page

    def build_embed(self) -> discord.Embed:
        profile = get_staff_profile(self.staff_id)

        if profile is None:
            return discord.Embed(
                title="找不到成員個人牆",
                description="這位成員的個人牆資料不存在或已被移除。",
                color=discord.Color.red(),
            )

        total = self._total_count()
        reviews = list_public_reviews_page(
            self.staff_id,
            page=self.page,
            page_size=self.page_size,
        )

        return build_reviews_page_embed(
            profile,
            reviews,
            page=self.page,
            page_size=self.page_size,
            total_count=total,
        )

    async def previous_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._refresh_button_state()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page = min(self._max_page(), self.page + 1)
        self._refresh_button_state()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


def build_staff_order_request_embed(profile: dict, requester_id: int | str) -> discord.Embed:
    staff_id = str(profile.get("staff_discord_id") or "")
    display_name = str(profile.get("display_name") or staff_id or "成員")
    profile_type = str(profile.get("profile_type") or "成員")
    role_title = str(profile.get("role_title") or "未填")
    games = str(profile.get("main_games") or "未填")
    services = str(profile.get("service_tags") or "未填")

    request_text = (
        f"我要指定：{display_name}（{staff_id}）\n"
        f"類型 / 階級：{profile_type} / {role_title}\n"
        f"遊戲：{games}\n"
        f"服務：{services}\n"
        "訂單內容：\n"
        "預計時間 / 場數：\n"
        "付款方式：\n"
        "備註："
    )

    embed = discord.Embed(
        title="指定下單請求",
        description=(
            f"你選擇指定 **{display_name}**。\n"
            "請把下方格式貼給客服，客服會確認內容、價格、成員是否可接。"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(),
    )

    embed.add_field(
        name="指定成員",
        value=(
            f"成員：<@{staff_id}>\n"
            f"類型：{profile_type}\n"
            f"階級：{role_title}\n"
            f"遊戲：{games}\n"
            f"服務：{services}"
        ),
        inline=False,
    )

    embed.add_field(
        name="給客服的複製格式",
        value=f"```txt\n{request_text[:1700]}\n```",
        inline=False,
    )

    embed.add_field(
        name="提醒",
        value=(
            "這個按鈕目前不會直接建立訂單，也不會鎖定成員。\n"
            "是否可接單、價格與指定費，仍以下單當下客服確認為準。"
        ),
        inline=False,
    )

    embed.set_footer(text="第一版只做請求卡片，避免影響現有訂單流程。")
    return embed



async def refresh_staff_profile_panel_for_staff(
    guild: discord.Guild | None,
    staff_id: int | str,
    *,
    reason: str = "event",
) -> bool:
    """Refresh one saved Discord staff profile panel after a data-changing event."""
    if guild is None:
        return False

    staff_id_text = str(staff_id or "").strip()
    if not staff_id_text:
        return False

    profile = get_staff_profile(staff_id_text)
    if profile is None:
        return False

    channel_id_text = str(
        profile.get("forum_thread_id")
        or profile.get("forum_channel_id")
        or ""
    ).strip()

    message_id_text = str(
        profile.get("panel_message_id")
        or ""
    ).strip()

    if not channel_id_text or not message_id_text:
        return False

    try:
        channel_id = int(channel_id_text)
        message_id = int(message_id_text)
    except (TypeError, ValueError):
        return False

    channel = None

    get_thread = getattr(guild, "get_thread", None)
    if callable(get_thread):
        channel = get_thread(channel_id)

    if channel is None:
        channel = guild.get_channel(channel_id)

    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return False

    if not hasattr(channel, "fetch_message"):
        return False

    try:
        panel_message = await channel.fetch_message(message_id)
    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException,
    ):
        return False

    latest_profile = get_staff_profile(staff_id_text)
    if latest_profile is None:
        return False

    try:
        await panel_message.edit(
            embed=build_staff_profile_embed(latest_profile),
            view=StaffProfilePanelView(staff_id_text),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
    except discord.HTTPException as exc:
        print(
            f"[staff-profile] refresh failed "
            f"staff_id={staff_id_text} "
            f"reason={reason}: {exc}"
        )
        return False

    print(
        f"[staff-profile] refreshed "
        f"staff_id={staff_id_text} "
        f"reason={reason}"
    )
    return True


def get_order_staff_ids_for_profile_refresh(
    *,
    ticket_channel_id: int | str | None = None,
    dispatch_message_id: int | str | None = None,
    order_id: int | str | None = None,
) -> list[str]:
    """Return active workers attached to one web order."""
    ensure_staff_profile_tables()

    conn = _connect()

    try:
        if (
            not _has_table(conn, "web_orders")
            or not _has_table(conn, "order_assignments")
        ):
            return []

        where = []
        params = []

        if order_id is not None and str(order_id).strip():
            where.append("id = ?")
            params.append(str(order_id))

        if ticket_channel_id is not None and str(ticket_channel_id).strip():
            where.append("ticket_channel_id = ?")
            params.append(str(ticket_channel_id))

        if dispatch_message_id is not None and str(dispatch_message_id).strip():
            where.append("dispatch_message_id = ?")
            params.append(str(dispatch_message_id))

        if not where:
            return []

        order_row = conn.execute(
            f"""
            SELECT id
            FROM web_orders
            WHERE {" OR ".join(where)}
            ORDER BY id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

        if order_row is None:
            return []

        rows = conn.execute(
            """
            SELECT DISTINCT worker_discord_id
            FROM order_assignments
            WHERE order_id = ?
              AND COALESCE(is_active, 1) = 1
              AND COALESCE(worker_discord_id, '') != ''
            ORDER BY id ASC
            """,
            (order_row["id"],),
        ).fetchall()

        return [
            str(row["worker_discord_id"])
            for row in rows
            if str(row["worker_discord_id"] or "").strip()
        ]

    finally:
        conn.close()


async def refresh_staff_profile_panels_for_order(
    guild: discord.Guild | None,
    *,
    ticket_channel_id: int | str | None = None,
    dispatch_message_id: int | str | None = None,
    order_id: int | str | None = None,
    reason: str = "order_event",
) -> int:
    """Refresh only the staff profile panels affected by one order."""
    staff_ids = get_order_staff_ids_for_profile_refresh(
        ticket_channel_id=ticket_channel_id,
        dispatch_message_id=dispatch_message_id,
        order_id=order_id,
    )

    refreshed = 0

    for staff_id in dict.fromkeys(staff_ids):
        try:
            ok = await refresh_staff_profile_panel_for_staff(
                guild,
                staff_id,
                reason=reason,
            )
        except Exception as exc:
            print(
                f"[staff-profile] event refresh error "
                f"staff_id={staff_id} "
                f"reason={reason}: {exc}"
            )
            continue

        if ok:
            refreshed += 1

    return refreshed


class StaffProfilePanelView(discord.ui.View):
    def __init__(self, staff_id: int | str):
        super().__init__(timeout=None)
        self.staff_id = str(staff_id)

        favorite_button = discord.ui.Button(
            label="♡ 收藏",
            style=discord.ButtonStyle.secondary,
            custom_id=f"staff_profile_favorite:{self.staff_id}",
            row=0,
        )
        favorite_button.callback = self.favorite_callback
        self.add_item(favorite_button)

        order_button = discord.ui.Button(
            label="指定下單",
            style=discord.ButtonStyle.primary,
            custom_id=f"staff_profile_order:{self.staff_id}",
            row=0,
        )
        order_button.callback = self.order_callback
        self.add_item(order_button)

        reviews_button = discord.ui.Button(
            label="查看評價",
            style=discord.ButtonStyle.secondary,
            custom_id=f"staff_profile_reviews:{self.staff_id}",
            row=0,
        )
        reviews_button.callback = self.reviews_callback
        self.add_item(reviews_button)

    async def favorite_callback(self, interaction: discord.Interaction):
        profile = get_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        favorited, message = toggle_staff_favorite(
            customer_id=interaction.user.id,
            staff_id=self.staff_id,
            staff_display_name=str(profile.get("display_name") or self.staff_id),
        )

        profile = get_staff_profile(self.staff_id)
        if profile is not None and interaction.message is not None:
            try:
                await interaction.message.edit(
                    embed=build_staff_profile_embed(profile),
                    view=StaffProfilePanelView(self.staff_id),
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"{message}\n成員：<@{self.staff_id}>",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def order_callback(self, interaction: discord.Interaction):
        profile = get_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message(
                "找不到這位成員的個人牆資料。",
                ephemeral=True,
            )
            return

        await _open_staff_profile_order_ticket(
            interaction,
            self.staff_id,
        )

    async def reviews_callback(self, interaction: discord.Interaction):
        profile = get_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        view = StaffProfileReviewsPageView(self.staff_id, page=0, page_size=5)
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )


def list_customer_favorites(customer_id: str, limit: int = 25) -> list[sqlite3.Row]:
    ensure_staff_profile_tables()

    conn = _connect()
    try:
        return conn.execute(
            """
            SELECT
                f.staff_discord_id,
                f.staff_display_name AS favorite_display_name,
                f.created_at AS favorited_at,
                p.display_name,
                p.profile_type,
                p.role_title,
                p.main_games,
                p.service_tags,
                p.bio,
                p.card_image_url,
                p.panel_message_id,
                p.forum_thread_id,
                p.is_public
            FROM staff_favorites f
            LEFT JOIN staff_profiles p
                   ON p.staff_discord_id = f.staff_discord_id
            WHERE f.customer_discord_id = ?
            ORDER BY f.created_at DESC, f.id DESC
            LIMIT ?
            """,
            (str(customer_id), int(limit)),
        ).fetchall()
    finally:
        conn.close()


def build_customer_favorites_embed(customer_id: str, favorites: list[sqlite3.Row]) -> discord.Embed:
    embed = discord.Embed(
        title="我的收藏成員",
        description="你收藏過的成員會顯示在這裡。指定下單目前仍需從票口或客服協助建立。",
        color=discord.Color.pink(),
    )

    if not favorites:
        embed.description = "你目前還沒有收藏成員。可以到成員個人牆按「♡ 收藏」。"
        return embed

    for index, row in enumerate(favorites[:25], start=1):
        staff_id = str(row["staff_discord_id"])
        display_name = (
            row["display_name"]
            or row["favorite_display_name"]
            or staff_id
        )

        profile_type = row["profile_type"] or "成員"
        role_title = row["role_title"] or "未填職位"
        games = row["main_games"] or "未填遊戲"
        services = row["service_tags"] or "未填服務"
        is_public = int(row["is_public"] or 0)

        if row["panel_message_id"] and row["forum_thread_id"]:
            wall_text = f"https://discord.com/channels/@me/{row['forum_thread_id']}/{row['panel_message_id']}"
        elif row["forum_thread_id"]:
            wall_text = f"<#{row['forum_thread_id']}>"
        else:
            wall_text = "尚未建立個人牆"

        public_text = "公開" if is_public else "未公開"

        embed.add_field(
            name=f"{index}. {display_name}",
            value=(
                f"成員：<@{staff_id}>\n"
                f"類型：{profile_type}｜{role_title}｜{public_text}\n"
                f"遊戲：{games}\n"
                f"服務：{services}\n"
                f"個人牆：{wall_text}"
            ),
            inline=False,
        )

    embed.set_footer(text="指定下單第一版暫不直接開單，避免影響現有訂單流程。")
    return embed


def _favorite_row_get(row, key: str, default=None):
    if row is None:
        return default

    if isinstance(row, dict):
        return row.get(key, default)

    try:
        return row[key]
    except Exception:
        return default


def _favorite_option_text(value, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        text = "未填"
    return text[: max(1, int(limit))]


def delete_customer_staff_favorite(customer_id: int | str, staff_id: int | str) -> bool:
    ensure_staff_profile_tables()

    conn = _connect()
    try:
        cur = conn.execute(
            """
            DELETE FROM staff_favorites
            WHERE customer_discord_id = ?
              AND staff_discord_id = ?
            """,
            (str(customer_id), str(staff_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def build_favorite_profile_summary_embed(customer_id: int | str, staff_id: int | str) -> discord.Embed:
    profile = get_staff_profile(str(staff_id))

    if profile is None:
        embed = discord.Embed(
            title="收藏成員",
            description="這位成員目前沒有公開個人牆資料，可能尚未建立或已被隱藏。",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(
            name="成員",
            value=f"<@{staff_id}>",
            inline=False,
        )
        embed.set_footer(text="你仍然可以取消收藏。")
        return embed

    embed = build_staff_profile_embed(profile)
    embed.add_field(
        name="收藏操作",
        value=(
            "你可以查看評價、產生指定下單請求卡片，或取消收藏。\n"
            "這裡不會直接建立訂單。"
        ),
        inline=False,
    )
    return embed


class CustomerFavoritesSelect(discord.ui.Select):
    def __init__(self, customer_id: int | str, favorites: list):
        self.customer_id = str(customer_id)
        safe_favorites = list(favorites or [])[:25]

        options = []

        for row in safe_favorites:
            staff_id = str(_favorite_row_get(row, "staff_discord_id", "") or "").strip()
            if not staff_id:
                continue

            display_name = (
                _favorite_row_get(row, "display_name")
                or _favorite_row_get(row, "favorite_display_name")
                or staff_id
            )
            role_title = _favorite_row_get(row, "role_title", "未填職位")
            games = _favorite_row_get(row, "main_games", "未填遊戲")
            services = _favorite_row_get(row, "service_tags", "未填服務")

            description = f"{role_title}｜{games}｜{services}"

            options.append(
                discord.SelectOption(
                    label=_favorite_option_text(display_name, 100),
                    value=staff_id[:100],
                    description=_favorite_option_text(description, 100),
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="目前沒有收藏成員",
                    value="__empty__",
                    description="到成員個人牆按 ♡ 收藏 後會出現在這裡",
                )
            )

        super().__init__(
            placeholder="選擇收藏成員",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.customer_id:
            await interaction.response.send_message("這不是你的收藏清單。", ephemeral=True)
            return

        staff_id = str(self.values[0] or "")

        if staff_id == "__empty__":
            await interaction.response.defer()
            return

        embed = build_favorite_profile_summary_embed(self.customer_id, staff_id)
        await interaction.response.edit_message(
            embed=embed,
            view=CustomerFavoriteActionsView(self.customer_id, staff_id),
        )


class CustomerFavoritesView(discord.ui.View):
    def __init__(self, customer_id: int | str, favorites: list):
        super().__init__(timeout=300)
        self.customer_id = str(customer_id)
        self.add_item(CustomerFavoritesSelect(customer_id, favorites))


class CustomerFavoriteActionsView(discord.ui.View):
    def __init__(self, customer_id: int | str, staff_id: int | str):
        super().__init__(timeout=300)
        self.customer_id = str(customer_id)
        self.staff_id = str(staff_id)

        summary_button = discord.ui.Button(
            label="個人牆摘要",
            style=discord.ButtonStyle.secondary,
            custom_id=f"favorite_summary:{self.staff_id}",
            row=0,
        )
        summary_button.callback = self.summary_callback
        self.add_item(summary_button)

        reviews_button = discord.ui.Button(
            label="查看評價",
            style=discord.ButtonStyle.secondary,
            custom_id=f"favorite_reviews:{self.staff_id}",
            row=0,
        )
        reviews_button.callback = self.reviews_callback
        self.add_item(reviews_button)

        order_button = discord.ui.Button(
            label="指定下單請求",
            style=discord.ButtonStyle.primary,
            custom_id=f"favorite_order_request:{self.staff_id}",
            row=1,
        )
        order_button.callback = self.order_request_callback
        self.add_item(order_button)

        remove_button = discord.ui.Button(
            label="取消收藏",
            style=discord.ButtonStyle.danger,
            custom_id=f"favorite_remove:{self.staff_id}",
            row=1,
        )
        remove_button.callback = self.remove_callback
        self.add_item(remove_button)

        back_button = discord.ui.Button(
            label="返回收藏清單",
            style=discord.ButtonStyle.secondary,
            custom_id=f"favorite_back:{self.staff_id}",
            row=2,
        )
        back_button.callback = self.back_callback
        self.add_item(back_button)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.customer_id:
            await interaction.response.send_message("這不是你的收藏操作。", ephemeral=True)
            return False
        return True

    async def summary_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=build_favorite_profile_summary_embed(self.customer_id, self.staff_id),
            view=self,
        )

    async def reviews_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        profile = get_staff_profile(self.staff_id)
        if profile is None:
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        view = StaffProfileReviewsPageView(self.staff_id, page=0, page_size=5)
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def order_request_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        profile = get_staff_profile(self.staff_id)
        if profile is None:
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=build_staff_order_request_embed(profile, interaction.user.id),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def remove_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        deleted = delete_customer_staff_favorite(self.customer_id, self.staff_id)
        favorites = list_customer_favorites(self.customer_id, limit=25)
        embed = build_customer_favorites_embed(self.customer_id, favorites)
        view = CustomerFavoritesView(self.customer_id, favorites) if favorites else None

        if deleted:
            embed.add_field(
                name="操作結果",
                value=f"已取消收藏 <@{self.staff_id}>。",
                inline=False,
            )
        else:
            embed.add_field(
                name="操作結果",
                value="這位成員已不在你的收藏清單中。",
                inline=False,
            )

        await interaction.response.edit_message(embed=embed, view=view)

    async def back_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        favorites = list_customer_favorites(self.customer_id, limit=25)
        embed = build_customer_favorites_embed(self.customer_id, favorites)
        view = CustomerFavoritesView(self.customer_id, favorites) if favorites else None

        await interaction.response.edit_message(embed=embed, view=view)



def _public_profile_value(row, key: str, default=None):
    if row is None:
        return default

    if isinstance(row, dict):
        return row.get(key, default)

    try:
        return row[key]
    except Exception:
        return default


def _public_profile_option_text(value, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        text = "未填"
    return text[: max(1, int(limit))]


def get_public_staff_profile(staff_id: int | str):
    profile = get_staff_profile(str(staff_id))

    if profile is None:
        return None

    try:
        is_public = int(profile.get("is_public") or 0) == 1
    except Exception:
        is_public = False

    if not is_public:
        return None

    return profile


def _normalize_public_profile_keyword(keyword: str | None) -> str:
    return str(keyword or "").strip()[:60]


def count_public_staff_profiles(keyword: str | None = None) -> int:
    ensure_staff_profile_tables()

    keyword = _normalize_public_profile_keyword(keyword)

    where = ["COALESCE(is_public, 1) = 1"]
    params = []

    if keyword:
        like = f"%{keyword.lower()}%"
        where.append(
            """
            (
                LOWER(COALESCE(display_name, '')) LIKE ?
                OR LOWER(COALESCE(profile_type, '')) LIKE ?
                OR LOWER(COALESCE(role_title, '')) LIKE ?
                OR LOWER(COALESCE(main_games, '')) LIKE ?
                OR LOWER(COALESCE(service_tags, '')) LIKE ?
                OR LOWER(COALESCE(bio, '')) LIKE ?
                OR LOWER(COALESCE(staff_discord_id, '')) LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like, like, like])

    sql = f"""
        SELECT COUNT(*) AS total
        FROM staff_profiles
        WHERE {' AND '.join(where)}
    """

    conn = _connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row["total"] or 0) if row is not None else 0
    finally:
        conn.close()


def list_public_staff_profiles(
    *,
    page: int = 0,
    page_size: int = 10,
    keyword: str | None = None,
) -> list[sqlite3.Row]:
    ensure_staff_profile_tables()

    page = max(0, int(page or 0))
    page_size = max(1, min(25, int(page_size or 10)))
    keyword = _normalize_public_profile_keyword(keyword)

    where = ["COALESCE(is_public, 1) = 1"]
    params = []

    if keyword:
        like = f"%{keyword.lower()}%"
        where.append(
            """
            (
                LOWER(COALESCE(display_name, '')) LIKE ?
                OR LOWER(COALESCE(profile_type, '')) LIKE ?
                OR LOWER(COALESCE(role_title, '')) LIKE ?
                OR LOWER(COALESCE(main_games, '')) LIKE ?
                OR LOWER(COALESCE(service_tags, '')) LIKE ?
                OR LOWER(COALESCE(bio, '')) LIKE ?
                OR LOWER(COALESCE(staff_discord_id, '')) LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like, like, like])

    params.extend([page_size, page * page_size])

    sql = f"""
        SELECT *
        FROM staff_profiles
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC, created_at DESC, display_name ASC
        LIMIT ?
        OFFSET ?
    """

    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def build_public_staff_profiles_embed(
    profiles: list,
    *,
    page: int = 0,
    page_size: int = 10,
    total_count: int = 0,
    keyword: str | None = None,
) -> discord.Embed:
    page = max(0, int(page or 0))
    page_size = max(1, min(25, int(page_size or 10)))
    total_count = max(0, int(total_count or 0))
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    keyword = _normalize_public_profile_keyword(keyword)

    description = (
        "選擇下方成員可以查看個人牆摘要、公開評價，或產生指定下單請求卡片。\n"
        "這裡只瀏覽公開個人牆，不會直接建立訂單。"
    )

    if keyword:
        description += f"\n\n搜尋關鍵字：`{keyword}`"

    embed = discord.Embed(
        title="公開成員個人牆",
        description=description,
        color=discord.Color.teal(),
        timestamp=datetime.now(),
    )

    embed.add_field(
        name="頁面",
        value=f"{page + 1} / {total_pages}｜共 {total_count} 位公開成員",
        inline=False,
    )

    if not profiles:
        embed.add_field(
            name="沒有符合的成員",
            value="目前沒有公開個人牆，或沒有符合搜尋條件的成員。",
            inline=False,
        )
        return embed

    for index, row in enumerate(profiles[:page_size], start=page * page_size + 1):
        staff_id = str(_public_profile_value(row, "staff_discord_id", "") or "")
        display_name = str(_public_profile_value(row, "display_name", "") or staff_id)
        profile_type = str(_public_profile_value(row, "profile_type", "") or "成員")
        role_title = str(_public_profile_value(row, "role_title", "") or "未填職位")
        games = str(_public_profile_value(row, "main_games", "") or "未填遊戲")
        services = str(_public_profile_value(row, "service_tags", "") or "未填服務")

        embed.add_field(
            name=f"{index}. {display_name}",
            value=(
                f"成員：<@{staff_id}>\n"
                f"類型：{profile_type}｜{role_title}\n"
                f"遊戲：{games}\n"
                f"服務：{services}"
            ),
            inline=False,
        )

    embed.set_footer(text="可用 /browse_staff_profiles keyword:關鍵字 搜尋名稱、遊戲、服務或階級。")
    return embed


def build_public_staff_profile_summary_embed(staff_id: int | str) -> discord.Embed:
    profile = get_public_staff_profile(staff_id)

    if profile is None:
        embed = discord.Embed(
            title="找不到公開個人牆",
            description="這位成員的個人牆不存在，或目前沒有公開。",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        return embed

    embed = build_staff_profile_embed(profile)
    embed.add_field(
        name="瀏覽操作",
        value=(
            "你可以查看公開評價，或產生指定下單請求卡片。\n"
            "這裡不會直接建立訂單。"
        ),
        inline=False,
    )
    return embed


class PublicStaffProfilesSelect(discord.ui.Select):
    def __init__(
        self,
        viewer_id: int | str,
        profiles: list,
        *,
        page: int = 0,
        page_size: int = 10,
        keyword: str | None = None,
    ):
        self.viewer_id = str(viewer_id)
        self.page = max(0, int(page or 0))
        self.page_size = max(1, min(25, int(page_size or 10)))
        self.keyword = _normalize_public_profile_keyword(keyword)

        options = []

        for row in list(profiles or [])[:25]:
            staff_id = str(_public_profile_value(row, "staff_discord_id", "") or "").strip()
            if not staff_id:
                continue

            display_name = (
                _public_profile_value(row, "display_name")
                or staff_id
            )
            role_title = _public_profile_value(row, "role_title", "未填職位")
            games = _public_profile_value(row, "main_games", "未填遊戲")
            services = _public_profile_value(row, "service_tags", "未填服務")

            description = f"{role_title}｜{games}｜{services}"

            options.append(
                discord.SelectOption(
                    label=_public_profile_option_text(display_name, 100),
                    value=staff_id[:100],
                    description=_public_profile_option_text(description, 100),
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="沒有可選擇的公開成員",
                    value="__empty__",
                    description="目前沒有公開個人牆",
                )
            )

        super().__init__(
            placeholder="選擇公開成員",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.viewer_id:
            await interaction.response.send_message("這不是你的瀏覽清單。", ephemeral=True)
            return

        staff_id = str(self.values[0] or "")

        if staff_id == "__empty__":
            await interaction.response.defer()
            return

        await interaction.response.edit_message(
            embed=build_public_staff_profile_summary_embed(staff_id),
            view=PublicStaffProfileActionsView(
                self.viewer_id,
                staff_id,
                keyword=self.keyword,
                page=self.page,
                page_size=self.page_size,
            ),
        )


class PublicStaffProfileBrowseView(discord.ui.View):
    def __init__(
        self,
        viewer_id: int | str,
        *,
        keyword: str | None = None,
        page: int = 0,
        page_size: int = 10,
    ):
        super().__init__(timeout=300)
        self.viewer_id = str(viewer_id)
        self.keyword = _normalize_public_profile_keyword(keyword)
        self.page = max(0, int(page or 0))
        self.page_size = max(1, min(25, int(page_size or 10)))

        self.total_count = count_public_staff_profiles(self.keyword)
        self.profiles = list_public_staff_profiles(
            page=self.page,
            page_size=self.page_size,
            keyword=self.keyword,
        )

        if self.profiles:
            self.add_item(
                PublicStaffProfilesSelect(
                    self.viewer_id,
                    self.profiles,
                    page=self.page,
                    page_size=self.page_size,
                    keyword=self.keyword,
                )
            )

        max_page = self._max_page()

        if max_page > 0:
            prev_button = discord.ui.Button(
                label="上一頁",
                style=discord.ButtonStyle.secondary,
                custom_id=f"public_profiles_prev:{self.page}",
                row=1,
                disabled=self.page <= 0,
            )
            prev_button.callback = self.previous_page
            self.add_item(prev_button)

            next_button = discord.ui.Button(
                label="下一頁",
                style=discord.ButtonStyle.secondary,
                custom_id=f"public_profiles_next:{self.page}",
                row=1,
                disabled=self.page >= max_page,
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

    def _max_page(self) -> int:
        return max(0, (self.total_count + self.page_size - 1) // self.page_size - 1)

    def build_embed(self) -> discord.Embed:
        return build_public_staff_profiles_embed(
            self.profiles,
            page=self.page,
            page_size=self.page_size,
            total_count=self.total_count,
            keyword=self.keyword,
        )

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.viewer_id:
            await interaction.response.send_message("這不是你的瀏覽清單。", ephemeral=True)
            return False
        return True

    async def previous_page(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        new_view = PublicStaffProfileBrowseView(
            self.viewer_id,
            keyword=self.keyword,
            page=max(0, self.page - 1),
            page_size=self.page_size,
        )
        await interaction.response.edit_message(embed=new_view.build_embed(), view=new_view if new_view.children else None)

    async def next_page(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        new_view = PublicStaffProfileBrowseView(
            self.viewer_id,
            keyword=self.keyword,
            page=min(self._max_page(), self.page + 1),
            page_size=self.page_size,
        )
        await interaction.response.edit_message(embed=new_view.build_embed(), view=new_view if new_view.children else None)


class PublicStaffProfileActionsView(discord.ui.View):
    def __init__(
        self,
        viewer_id: int | str,
        staff_id: int | str,
        *,
        keyword: str | None = None,
        page: int = 0,
        page_size: int = 10,
    ):
        super().__init__(timeout=300)
        self.viewer_id = str(viewer_id)
        self.staff_id = str(staff_id)
        self.keyword = _normalize_public_profile_keyword(keyword)
        self.page = max(0, int(page or 0))
        self.page_size = max(1, min(25, int(page_size or 10)))

        summary_button = discord.ui.Button(
            label="個人牆摘要",
            style=discord.ButtonStyle.secondary,
            custom_id=f"public_profile_summary:{self.staff_id}",
            row=0,
        )
        summary_button.callback = self.summary_callback
        self.add_item(summary_button)

        reviews_button = discord.ui.Button(
            label="查看評價",
            style=discord.ButtonStyle.secondary,
            custom_id=f"public_profile_reviews:{self.staff_id}",
            row=0,
        )
        reviews_button.callback = self.reviews_callback
        self.add_item(reviews_button)

        order_button = discord.ui.Button(
            label="指定下單請求",
            style=discord.ButtonStyle.primary,
            custom_id=f"public_profile_order:{self.staff_id}",
            row=1,
        )
        order_button.callback = self.order_request_callback
        self.add_item(order_button)

        back_button = discord.ui.Button(
            label="返回瀏覽",
            style=discord.ButtonStyle.secondary,
            custom_id=f"public_profile_back:{self.staff_id}",
            row=1,
        )
        back_button.callback = self.back_callback
        self.add_item(back_button)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.viewer_id:
            await interaction.response.send_message("這不是你的瀏覽操作。", ephemeral=True)
            return False
        return True

    async def summary_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=build_public_staff_profile_summary_embed(self.staff_id),
            view=self,
        )

    async def reviews_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        profile = get_public_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message("這位成員目前沒有公開個人牆。", ephemeral=True)
            return

        view = StaffProfileReviewsPageView(self.staff_id, page=0, page_size=5)
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def order_request_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        profile = get_public_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message("這位成員目前沒有公開個人牆。", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=build_staff_order_request_embed(profile, interaction.user.id),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def back_callback(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return

        view = PublicStaffProfileBrowseView(
            self.viewer_id,
            keyword=self.keyword,
            page=self.page,
            page_size=self.page_size,
        )

        await interaction.response.edit_message(
            embed=view.build_embed(),
            view=view if view.children else None,
        )

