from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import discord


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

        review_count = 0
        average_rating = None
        if _has_table(conn, "order_reviews"):
            row = conn.execute(
                """
                SELECT COUNT(*) AS c,
                       AVG(rating) AS avg_rating
                FROM order_reviews
                WHERE staff_discord_id = ?
                  AND COALESCE(is_public, 1) = 1
                  AND COALESCE(is_hidden, 0) = 0
                """,
                (staff_id_text,),
            ).fetchone()
            review_count = int(row["c"] or 0)
            average_rating = row["avg_rating"]

        return {
            "favorite_count": int(favorite_count or 0),
            "completed_orders": int(completed_orders or 0),
            "review_count": int(review_count or 0),
            "average_rating": float(average_rating) if average_rating is not None else None,
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
            f"⭐ 平均評價：{rating_text}"
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
        f"✅ 完成訂單：{stats['completed_orders']}"
        if avg is not None
        else (
            "⭐ 平均：尚無公開評價\n"
            f"📝 公開評價：{stats['review_count']} 則\n"
            f"✅ 完成訂單：{stats['completed_orders']}"
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
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        display_name = str(profile.get("display_name") or self.staff_id)
        await interaction.response.send_message(
            (
                f"已選擇指定：**{display_name}**。\n\n"
                "目前第一版不直接建立訂單，避免影響現有訂單流程。\n"
                "請到下單票口告知客服要指定這位成員，客服會確認內容、價格與是否可接。"
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def reviews_callback(self, interaction: discord.Interaction):
        profile = get_staff_profile(self.staff_id)

        if profile is None:
            await interaction.response.send_message("找不到這位成員的個人牆資料。", ephemeral=True)
            return

        reviews = list_public_reviews(self.staff_id, limit=5)
        await interaction.response.send_message(
            embed=build_reviews_embed(profile, reviews),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )
