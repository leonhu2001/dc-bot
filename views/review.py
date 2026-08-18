from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

import discord

from views.staff_profiles import refresh_staff_profile_panel_for_staff

from core.permissions import is_customer_staff


_REVIEW_CHANNEL_ID: int | None = None
_REORDER_TICKET_CREATOR = None


def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()


def configure_reorder_ticket_creator(callback) -> None:
    global _REORDER_TICKET_CREATOR
    _REORDER_TICKET_CREATOR = callback




def get_review_channel_id() -> int:
    if _REVIEW_CHANNEL_ID is None:
        raise RuntimeError("Review views are not configured: REVIEW_CHANNEL_ID is missing")
    return _REVIEW_CHANNEL_ID


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


def ensure_review_tables() -> None:
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

            CREATE INDEX IF NOT EXISTS idx_order_reviews_order_id
                ON order_reviews(order_id);

            CREATE INDEX IF NOT EXISTS idx_order_reviews_staff
                ON order_reviews(staff_discord_id);

            CREATE INDEX IF NOT EXISTS idx_order_reviews_ticket
                ON order_reviews(ticket_channel_id);

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

            CREATE INDEX IF NOT EXISTS idx_order_review_skips_order_id
                ON order_review_skips(order_id);

            CREATE INDEX IF NOT EXISTS idx_order_review_skips_ticket
                ON order_review_skips(ticket_channel_id);

            CREATE TABLE IF NOT EXISTS staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                source TEXT NOT NULL DEFAULT 'post_close',
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


def rating_to_stars(rating_text: str) -> tuple[int | None, str | None]:
    try:
        rating = int(str(rating_text).strip())
    except ValueError:
        return None, None

    if rating < 1 or rating > 5:
        return None, None

    return rating, "⭐" * rating


def is_public_answer(text: str | None) -> bool:
    value = str(text or "").strip().lower()
    if value in {"否", "不", "不公開", "no", "n", "false", "0"}:
        return False
    return True


def can_operate_review(interaction: discord.Interaction, customer_id: int) -> bool:
    is_customer = interaction.user.id == customer_id
    is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)
    return is_customer or is_staff


def _find_order(ticket_channel_id: int | str | None, dispatch_message_id: int | str | None = None) -> sqlite3.Row | None:
    ensure_review_tables()
    conn = _connect()
    try:
        params: list[str] = []
        where: list[str] = []

        if ticket_channel_id is not None:
            where.append("ticket_channel_id = ?")
            params.append(str(ticket_channel_id))

        if dispatch_message_id is not None:
            where.append("dispatch_message_id = ?")
            params.append(str(dispatch_message_id))

        if not where:
            return None

        row = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE {" OR ".join(where)}
            ORDER BY id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return row
    finally:
        conn.close()


def get_review_targets(ticket_channel_id: int | str | None, dispatch_message_id: int | str | None = None) -> tuple[sqlite3.Row | None, list[dict]]:
    order = _find_order(ticket_channel_id, dispatch_message_id)
    if order is None:
        return None, []

    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT worker_discord_id, worker_display_name, role_type
            FROM order_assignments
            WHERE order_id = ?
              AND COALESCE(is_active, 1) = 1
            ORDER BY assigned_at ASC, id ASC
            """,
            (order["id"],),
        ).fetchall()

        targets = []
        seen = set()

        for row in rows:
            staff_id = str(row["worker_discord_id"] or "").strip()
            if not staff_id or staff_id in seen:
                continue

            seen.add(staff_id)
            targets.append(
                {
                    "staff_id": staff_id,
                    "display_name": str(row["worker_display_name"] or staff_id),
                    "role_type": str(row["role_type"] or ""),
                }
            )

        return order, targets
    finally:
        conn.close()


def _existing_reviews(order_id: int | None, ticket_channel_id: int | str | None) -> dict[str, sqlite3.Row]:
    ensure_review_tables()
    conn = _connect()
    try:
        if order_id is not None:
            rows = conn.execute(
                """
                SELECT *
                FROM order_reviews
                WHERE order_id = ?
                ORDER BY id DESC
                """,
                (order_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM order_reviews
                WHERE ticket_channel_id = ?
                ORDER BY id DESC
                """,
                (str(ticket_channel_id),),
            ).fetchall()

        result = {}
        for row in rows:
            staff_id = str(row["staff_discord_id"] or "")
            if staff_id and staff_id not in result:
                result[staff_id] = row
        return result
    finally:
        conn.close()


def _has_skipped_all(order_id: int | None, ticket_channel_id: int | str | None) -> bool:
    ensure_review_tables()
    conn = _connect()
    try:
        if order_id is not None:
            row = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE order_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE ticket_channel_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (str(ticket_channel_id),),
            ).fetchone()

        return row is not None
    finally:
        conn.close()


def build_review_status(ticket_channel_id: int | str, customer_id: int) -> tuple[sqlite3.Row | None, list[dict], bool]:
    order, targets = get_review_targets(ticket_channel_id)
    order_id = int(order["id"]) if order is not None else None
    existing = _existing_reviews(order_id, ticket_channel_id)
    skipped_all = _has_skipped_all(order_id, ticket_channel_id)

    enriched = []
    for target in targets:
        row = existing.get(str(target["staff_id"]))
        item = dict(target)
        item["reviewed"] = row is not None
        item["rating"] = int(row["rating"]) if row is not None else None
        item["skipped"] = skipped_all
        enriched.append(item)

    return order, enriched, skipped_all


def record_review_skip(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str | None,
    dispatch_message_id: int | str | None,
    customer_id: int,
    targets: list[dict],
) -> None:
    ensure_review_tables()
    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None
    receipt_id = str(order["bot_order_no"] or "") if order is not None else ""

    conn = _connect()
    try:
        existing = None
        if order_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE order_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
        elif ticket_channel_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE ticket_channel_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (str(ticket_channel_id),),
            ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO order_review_skips (
                    order_id,
                    ticket_channel_id,
                    dispatch_message_id,
                    receipt_id,
                    customer_discord_id,
                    staff_discord_id,
                    skipped_all,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 1, 'discord', ?)
                """,
                (
                    order_id,
                    str(ticket_channel_id or ""),
                    str(dispatch_message_id or (order["dispatch_message_id"] if order is not None else "") or ""),
                    receipt_id,
                    str(customer_id),
                    now,
                ),
            )

        for target in targets:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue

            exists = None
            if order_id is not None:
                exists = conn.execute(
                    """
                    SELECT id
                    FROM order_review_skips
                    WHERE order_id = ?
                      AND staff_discord_id = ?
                    LIMIT 1
                    """,
                    (order_id, staff_id),
                ).fetchone()

            if exists is None:
                conn.execute(
                    """
                    INSERT INTO order_review_skips (
                        order_id,
                        ticket_channel_id,
                        dispatch_message_id,
                        receipt_id,
                        customer_discord_id,
                        staff_discord_id,
                        skipped_all,
                        source,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, 'discord', ?)
                    """,
                    (
                        order_id,
                        str(ticket_channel_id or ""),
                        str(dispatch_message_id or (order["dispatch_message_id"] if order is not None else "") or ""),
                        receipt_id,
                        str(customer_id),
                        staff_id,
                        now,
                    ),
                )

        conn.commit()
    finally:
        conn.close()


def record_member_review(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str,
    staff_id: str,
    staff_display_name: str,
    customer_id: int,
    rating: int,
    comment: str,
    is_public: bool,
    order_content: str | None,
) -> tuple[bool, str]:
    ensure_review_tables()
    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None

    conn = _connect()
    try:
        if order_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_reviews
                WHERE order_id = ?
                  AND staff_discord_id = ?
                LIMIT 1
                """,
                (order_id, str(staff_id)),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT id
                FROM order_reviews
                WHERE ticket_channel_id = ?
                  AND staff_discord_id = ?
                LIMIT 1
                """,
                (str(ticket_channel_id), str(staff_id)),
            ).fetchone()

        if existing is not None:
            return False, "這位成員已經評價過了，不能重複評價。"

        conn.execute(
            """
            INSERT INTO order_reviews (
                order_id,
                ticket_channel_id,
                dispatch_message_id,
                receipt_id,
                staff_discord_id,
                staff_display_name,
                customer_discord_id,
                rating,
                comment,
                service_category,
                service_item,
                order_content,
                is_public,
                is_hidden,
                source,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'discord', ?, ?)
            """,
            (
                order_id,
                str(ticket_channel_id),
                str(order["dispatch_message_id"] or "") if order is not None else "",
                str(order["bot_order_no"] or "") if order is not None else "",
                str(staff_id),
                str(staff_display_name or staff_id),
                str(customer_id),
                int(rating),
                str(comment or "").strip(),
                str(order["category"] or "") if order is not None else "",
                str(order["item"] or "") if order is not None else "",
                str(order_content or ""),
                1 if is_public else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return True, "評價已送出。"
    finally:
        conn.close()



def get_staff_favorites(customer_id: int | str, staff_ids: list[str] | None = None) -> set[str]:
    ensure_review_tables()
    conn = _connect()
    try:
        params: list[str] = [str(customer_id)]
        where = "customer_discord_id = ?"

        if staff_ids:
            placeholders = ",".join("?" for _ in staff_ids)
            where += f" AND staff_discord_id IN ({placeholders})"
            params.extend(str(item) for item in staff_ids)

        rows = conn.execute(
            f"""
            SELECT staff_discord_id
            FROM staff_favorites
            WHERE {where}
            """,
            params,
        ).fetchall()

        return {str(row["staff_discord_id"]) for row in rows}
    finally:
        conn.close()


def add_staff_favorite(
    *,
    customer_id: int | str,
    staff_id: int | str,
    staff_display_name: str | None = None,
    source: str = "post_close",
) -> bool:
    ensure_review_tables()
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
                str(source or "post_close"),
                now,
            ),
        )
        conn.commit()
        return conn.total_changes > before
    finally:
        conn.close()



def build_reorder_summary(order, targets: list[dict], order_content: str | None = None) -> str:
    if order is None:
        base_lines = [
            "找不到網站訂單資料，請客服依照票口內容協助再約。",
        ]
    else:
        base_lines = [
            f"訂單：WEB-{order['id']}",
            f"分類：{order['category'] or '未記錄'}",
            f"項目：{order['item'] or '未記錄'}",
            f"數量：{order['quantity'] or 1}",
            f"原金額：{order['amount'] or 0}",
            f"付款方式：{order['payment_method'] or '未記錄'}",
        ]

        note = str(order["note"] or "").strip()
        if note:
            base_lines.append(f"原備註：{note}")

    if order_content:
        base_lines.append(f"票口內容：{str(order_content).strip()}")

    if targets:
        base_lines.append("")
        base_lines.append("本次接單成員：")
        for target in targets:
            base_lines.append(f"- {_target_label(target)}")
    else:
        base_lines.append("")
        base_lines.append("本次接單成員：未找到網站接單資料")

    return "\n".join(base_lines)


def _target_label(target: dict) -> str:
    name = str(target.get("display_name") or target.get("staff_id") or "成員")
    staff_id = str(target.get("staff_id") or "")
    if staff_id:
        return f"{name}｜<@{staff_id}>"
    return name


async def _send_review_channel_embed(
    *,
    guild: discord.Guild,
    customer_id: int,
    target: dict,
    rating: int,
    comment: str,
    is_public: bool,
    order_content: str | None,
) -> None:
    """評價只寫入網站 DB，不再轉發到 Discord 評價頻道。

    舊的 REVIEW_CHANNEL_ID 保留給相容設定用，但這裡不再發訊息，
    之後刪除舊評價頻道也不會影響結單後評價流程。
    """
    return


class MemberReviewModal(discord.ui.Modal, title="評價指定成員"):
    rating = discord.ui.TextInput(
        label="星等",
        placeholder="請輸入 1～5",
        required=True,
        max_length=1,
    )
    comment = discord.ui.TextInput(
        label="評語",
        placeholder="可空白；例如：報點清楚、很穩、很有耐心",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )
    public_answer = discord.ui.TextInput(
        label="是否公開到個人牆",
        placeholder="空白或輸入「是」=公開；輸入「否」=不公開",
        required=False,
        max_length=10,
    )

    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        order_content: str | None,
        target: dict,
    ):
        super().__init__()
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以留下評價。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        rating_number, stars = rating_to_stars(self.rating.value)
        if rating_number is None:
            await interaction.response.send_message("星等請輸入 1～5 的數字。", ephemeral=True)
            return

        order, _targets = get_review_targets(self.ticket_channel_id)
        ok, message = record_member_review(
            order=order,
            ticket_channel_id=self.ticket_channel_id,
            staff_id=str(self.target.get("staff_id")),
            staff_display_name=str(self.target.get("display_name") or self.target.get("staff_id")),
            customer_id=self.customer_id,
            rating=rating_number,
            comment=str(self.comment.value or ""),
            is_public=is_public_answer(self.public_answer.value),
            order_content=self.order_content,
        )

        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return

        await refresh_staff_profile_panel_for_staff(
            guild,
            str(self.target.get("staff_id") or ""),
            reason="review_submitted",
        )

        await _send_review_channel_embed(
            guild=guild,
            customer_id=self.customer_id,
            target=self.target,
            rating=rating_number,
            comment=str(self.comment.value or ""),
            is_public=is_public_answer(self.public_answer.value),
            order_content=self.order_content,
        )

        _order, statuses, _skipped_all = build_review_status(self.ticket_channel_id, self.customer_id)
        all_done = bool(statuses) and all(bool(item.get("reviewed")) for item in statuses)

        text = (
            f"已送出 {_target_label(self.target)} 的評價：{stars}\n\n"
            "全部成員都已評價完成，可以回到票口按「關閉票口」。"
            if all_done
            else f"已送出 {_target_label(self.target)} 的評價：{stars}\n\n還可以繼續評價其他成員。"
        )

        await interaction.response.send_message(
            text,
            ephemeral=True,
            view=MemberReviewMenuView(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                order_content=self.order_content,
            ),
        )


class MemberReviewSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, order_content: str | None, targets: list[dict]):
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content
        self.targets = targets

        options = []
        for target in targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            reviewed = bool(target.get("reviewed"))
            label = str(target.get("display_name") or staff_id or "成員")[:80]
            desc = "已評價" if reviewed else "尚未評價"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=staff_id,
                    description=desc,
                    emoji="✅" if reviewed else "⭐",
                )
            )

        super().__init__(
            placeholder="選擇要評價的成員",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以留下評價。", ephemeral=True)
            return

        staff_id = str(self.values[0])
        target = next((item for item in self.targets if str(item.get("staff_id")) == staff_id), None)

        if target is None:
            await interaction.response.send_message("找不到這位成員，請重新打開評價面板。", ephemeral=True)
            return

        if target.get("reviewed"):
            await interaction.response.send_message("這位成員已經評價過了。", ephemeral=True)
            return

        await interaction.response.send_modal(
            MemberReviewModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                order_content=self.order_content,
                target=target,
            )
        )


class MemberReviewMenuView(discord.ui.View):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, order_content: str | None = None):
        super().__init__(timeout=900)
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content

        _order, targets, skipped_all = build_review_status(ticket_channel_id, customer_id)
        if targets and not skipped_all:
            self.add_item(
                MemberReviewSelect(
                    customer_id=customer_id,
                    ticket_channel_id=ticket_channel_id,
                    order_content=order_content,
                    targets=targets,
                )
            )



class FavoriteCurrentMembersSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, targets: list[dict]):
        self.customer_id = customer_id
        self.targets = targets
        favorite_ids = get_staff_favorites(
            customer_id,
            [str(item.get("staff_id") or "") for item in targets],
        )

        options = []
        for target in targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue

            already = staff_id in favorite_ids
            label = str(target.get("display_name") or staff_id or "成員")[:80]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=staff_id,
                    description="已收藏" if already else "加入我的收藏",
                    emoji="❤️" if already else "♡",
                    default=False,
                )
            )

        super().__init__(
            placeholder="選擇要收藏的本次成員",
            min_values=1,
            max_values=max(1, min(len(options), 25)),
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以收藏成員。", ephemeral=True)
            return

        selected_ids = {str(value) for value in self.values}
        added = []
        already = []

        for target in self.targets:
            staff_id = str(target.get("staff_id") or "")
            if staff_id not in selected_ids:
                continue

            display_name = str(target.get("display_name") or staff_id)
            inserted = add_staff_favorite(
                customer_id=self.customer_id,
                staff_id=staff_id,
                staff_display_name=display_name,
                source="post_close",
            )

            if inserted:
                added.append(display_name)
            else:
                already.append(display_name)

        lines = []
        if added:
            lines.append("已收藏：" + "、".join(added))
        if already:
            lines.append("原本已收藏：" + "、".join(already))

        if not lines:
            lines.append("沒有新增收藏。")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        guild = interaction.guild
        if guild is not None:
            for staff_id in selected_ids:
                await refresh_staff_profile_panel_for_staff(
                    guild,
                    staff_id,
                    reason="post_close_favorite",
                )


class FavoriteCurrentMembersView(discord.ui.View):
    def __init__(self, *, customer_id: int, targets: list[dict]):
        super().__init__(timeout=300)
        self.customer_id = customer_id
        self.targets = targets

        if targets:
            self.add_item(FavoriteCurrentMembersSelect(customer_id=customer_id, targets=targets))


class ConfirmCloseTicketView(discord.ui.View):
    def __init__(self, *, customer_id: int):
        super().__init__(timeout=60)
        self.customer_id = customer_id

    @discord.ui.button(label="確認關閉票口", style=discord.ButtonStyle.danger, custom_id="post_close_confirm_delete_ticket")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以關閉票口。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        await interaction.response.send_message("已確認關閉票口，頻道將在 3 秒後刪除。", ephemeral=True)

        try:
            await channel.send(
                f"{interaction.user.mention} 已確認關閉票口，頻道將在 3 秒後刪除。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

        await asyncio.sleep(3)
        await channel.delete(reason=f"Closed post-order ticket by {interaction.user}")

    @discord.ui.button(label="先不要關閉", style=discord.ButtonStyle.secondary, custom_id="post_close_keep_ticket")
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已保留票口。", ephemeral=True)


class ReviewButtonView(discord.ui.View):
    def __init__(self, customer_id: int, order_content: str | None = None):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.order_content = order_content
        ensure_review_tables()

    @discord.ui.button(
        label="⭐ 評價本次服務",
        style=discord.ButtonStyle.success,
        custom_id="review_leave_button",
        row=0,
    )
    async def leave_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以留下評價。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        order, targets, skipped_all = build_review_status(channel.id, self.customer_id)

        if skipped_all:
            await interaction.response.send_message("這張單已經選擇不留評價。", ephemeral=True)
            return

        if not targets:
            await interaction.response.send_message(
                "這張單目前找不到接單成員資料，因此無法分別評價。\n"
                "可以請客服確認網站接單資料，或直接按「不留評價 / 關閉票口」。",
                ephemeral=True,
            )
            return

        lines = [
            "請選擇要評價的成員：",
            "",
        ]

        for item in targets:
            status = f"已評價 ⭐ {item['rating']}" if item.get("reviewed") else "尚未評價"
            lines.append(f"{_target_label(item)}｜{status}")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
            view=MemberReviewMenuView(
                customer_id=self.customer_id,
                ticket_channel_id=channel.id,
                order_content=self.order_content,
            ),
        )

    @discord.ui.button(
        label="不留評價",
        style=discord.ButtonStyle.secondary,
        custom_id="review_skip_button",
        row=0,
    )
    async def skip_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以操作。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        order, targets = get_review_targets(channel.id)
        record_review_skip(
            order=order,
            ticket_channel_id=channel.id,
            dispatch_message_id=order["dispatch_message_id"] if order is not None else None,
            customer_id=self.customer_id,
            targets=targets,
        )

        for child in self.children:
            if getattr(child, "custom_id", "") in {"review_leave_button", "review_skip_button"}:
                child.disabled = True

        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "已記錄不留評價。票口不會自動關閉，需要時可以按「關閉票口」。",
            ephemeral=True,
        )

        try:
            await channel.send(
                f"{interaction.user.mention} 已選擇不留評價。需要時可按「關閉票口」。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="❤️ 收藏本次成員",
        style=discord.ButtonStyle.secondary,
        custom_id="review_favorite_members_button",
        row=1,
    )
    async def favorite_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以收藏成員。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        _order, targets = get_review_targets(channel.id)

        if not targets:
            await interaction.response.send_message(
                "這張單目前找不到接單成員資料，暫時無法收藏本次成員。",
                ephemeral=True,
            )
            return

        favorite_ids = get_staff_favorites(
            self.customer_id,
            [str(item.get("staff_id") or "") for item in targets],
        )

        lines = [
            "選擇要加入收藏的本次成員：",
            "",
        ]

        for item in targets:
            staff_id = str(item.get("staff_id") or "")
            status = "已收藏" if staff_id in favorite_ids else "尚未收藏"
            lines.append(f"{_target_label(item)}｜{status}")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
            view=FavoriteCurrentMembersView(
                customer_id=self.customer_id,
                targets=targets,
            ),
        )

    @discord.ui.button(
        label="🔁 再約",
        style=discord.ButtonStyle.primary,
        custom_id="review_reorder_button",
        row=1,
    )
    async def reorder(self, interaction: discord.Interaction, button: discord.ui.Button):
        # reorder_v2_direct_self_service
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以使用再約。",
                ephemeral=True,
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True,
            )
            return

        order, targets = get_review_targets(
            channel.id
        )

        if order is None:
            await interaction.response.send_message(
                "找不到這張已結單訂單的網站資料，暫時無法自動建立再約單。",
                ephemeral=True,
            )
            return

        creator = _REORDER_TICKET_CREATOR

        if creator is None:
            await interaction.response.send_message(
                "再約系統尚未完成初始化，請通知客服。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            result = await creator(
                interaction=interaction,
                order=order,
                targets=targets,
                order_content=self.order_content,
            )
        except Exception as exc:
            print(
                f"[reorder] create ticket failed "
                f"customer_id={self.customer_id} "
                f"ticket_channel_id={channel.id}: "
                f"{type(exc).__name__}: {exc}"
            )

            await interaction.followup.send(
                "建立再約票口失敗，請通知客服確認機器人紀錄。",
                ephemeral=True,
            )
            return

        if not isinstance(result, dict):
            await interaction.followup.send(
                "再約系統回傳資料異常，請通知客服。",
                ephemeral=True,
            )
            return

        new_channel = result.get("channel")

        if not isinstance(
            new_channel,
            discord.TextChannel,
        ):
            await interaction.followup.send(
                "沒有成功建立再約票口，請通知客服。",
                ephemeral=True,
            )
            return

        created = bool(
            result.get("created", True)
        )

        warning = str(
            result.get("warning")
            or ""
        ).strip()

        if created:
            text = (
                f"已建立再約票口：{new_channel.mention}\n"
                "系統已先帶入上一張單的內容，你可以直接進去修改。\n"
                "確認完成後由客服按「客服確認送出」。"
            )
        else:
            text = (
                f"你已經有一張這筆訂單的再約草稿：{new_channel.mention}\n"
                "直接進去修改即可，不會重複建立票口。"
            )

        if warning:
            text += (
                "\n\n提醒："
                + warning
            )

        await interaction.followup.send(
            text,
            ephemeral=True,
        )


    @discord.ui.button(
        label="關閉票口",
        style=discord.ButtonStyle.danger,
        custom_id="review_close_ticket_button",
        row=1,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以關閉票口。", ephemeral=True)
            return

        await interaction.response.send_message(
            "確定要關閉這個票口嗎？",
            ephemeral=True,
            view=ConfirmCloseTicketView(customer_id=self.customer_id),
        )
