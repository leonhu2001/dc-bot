from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord

from views.staff_profiles import refresh_staff_profile_panel_for_staff

from core.permissions import is_customer_staff
from services.ticket_archives import save_ticket_archive


_REVIEW_CHANNEL_ID: int | None = None
_REORDER_TICKET_CREATOR = None
_WORKER_TIP_WALLET_HANDLER = None
_WORKER_TIP_LOG_HANDLER = None

WORKER_TIP_POLICY_TEXT = (
    "🍗 **加雞腿說明**\n"
    "• 雞腿金額 100% 給你指定的打手／陪玩。\n"
    "• 雞腿採獨立帳務，不併入原訂單金額。\n"
    "• 雞腿不計原單抽成，也不影響原訂單分潤。\n"
    "• 雞腿不列入 VIP 累積消費，也不增加會員點數。\n"
    "• 使用「我的錢包」會立即扣款；街口／轉帳送出後會進網站審核，請在票口貼付款截圖，客服確認後才會入帳。"
)


def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()


def configure_reorder_ticket_creator(callback) -> None:
    global _REORDER_TICKET_CREATOR
    _REORDER_TICKET_CREATOR = callback


def configure_worker_tip_callbacks(*, wallet_handler=None, log_handler=None) -> None:
    global _WORKER_TIP_WALLET_HANDLER, _WORKER_TIP_LOG_HANDLER
    _WORKER_TIP_WALLET_HANDLER = wallet_handler
    _WORKER_TIP_LOG_HANDLER = log_handler
    ensure_review_tables()


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
                customer_display_name TEXT,
                customer_name_public INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                wallet_transaction_id INTEGER,
                confirmation_message_id TEXT,
                confirmed_by_discord_id TEXT,
                confirmed_by_display_name TEXT,
                paid_at TEXT,
                payout_paid_at TEXT,
                cancelled_at TEXT,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_worker_tips_order
                ON worker_tips(order_id);

            CREATE INDEX IF NOT EXISTS idx_worker_tips_ticket
                ON worker_tips(ticket_channel_id);

            CREATE INDEX IF NOT EXISTS idx_worker_tips_worker
                ON worker_tips(worker_discord_id);

            CREATE INDEX IF NOT EXISTS idx_worker_tips_payment
                ON worker_tips(payment_status, payout_status);
            """
        )
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(order_reviews)"
            ).fetchall()
        }

        if "customer_display_name" not in columns:
            conn.execute(
                "ALTER TABLE order_reviews "
                "ADD COLUMN customer_display_name TEXT"
            )

        if "customer_name_public" not in columns:
            conn.execute(
                "ALTER TABLE order_reviews "
                "ADD COLUMN customer_name_public INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute(
            """
            UPDATE order_reviews
            SET customer_name_public = 0
            WHERE customer_name_public IS NULL
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


def is_customer_name_public_answer(text: str | None) -> bool:
    value = str(text or "").strip().lower()
    return value in {
        "是",
        "公開",
        "公開姓名",
        "要",
        "yes",
        "y",
        "true",
        "1",
    }


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
        item["comment"] = str(row["comment"] or "") if row is not None else ""
        item["customer_name_public"] = (
            bool(row["customer_name_public"])
            if row is not None and "customer_name_public" in row.keys()
            else False
        )
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
    customer_display_name: str,
    customer_name_public: bool,
    rating: int,
    comment: str,
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
                customer_display_name,
                customer_name_public,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'discord', ?, ?)
            """,
            (
                order_id,
                str(ticket_channel_id),
                str(order["dispatch_message_id"] or "") if order is not None else "",
                str(order["bot_order_no"] or "") if order is not None else "",
                str(staff_id),
                str(staff_display_name or staff_id),
                str(customer_id),
                str(customer_display_name or "").strip(),
                1 if customer_name_public else 0,
                int(rating),
                str(comment or "").strip(),
                str(order["category"] or "") if order is not None else "",
                str(order["item"] or "") if order is not None else "",
                str(order_content or ""),
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


def _get_post_close_tip_rows(ticket_channel_id: int | str) -> list[sqlite3.Row]:
    ensure_review_tables()
    conn = _connect()
    try:
        return conn.execute(
            """
            SELECT
                worker_discord_id,
                worker_display_name,
                amount,
                payment_method,
                payment_status
            FROM worker_tips
            WHERE ticket_channel_id = ?
              AND payment_status <> 'cancelled'
            ORDER BY id ASC
            """,
            (str(ticket_channel_id),),
        ).fetchall()
    finally:
        conn.close()


def get_post_close_status(ticket_channel_id: int | str, customer_id: int | str) -> dict:
    _order, targets, skipped_all = build_review_status(
        ticket_channel_id,
        int(customer_id),
    )

    target_ids = [
        str(item.get("staff_id") or "")
        for item in targets
        if str(item.get("staff_id") or "")
    ]
    favorite_ids = get_staff_favorites(customer_id, target_ids)
    tip_rows = _get_post_close_tip_rows(ticket_channel_id)

    paid_total = 0
    pending_total = 0
    for row in tip_rows:
        amount = int(row["amount"] or 0)
        status = str(row["payment_status"] or "")
        if status == "paid":
            paid_total += amount
        elif status in {"pending", "pending_review"}:
            pending_total += amount

    return {
        "targets": targets,
        "skipped_all": bool(skipped_all),
        "favorite_ids": favorite_ids,
        "tip_rows": tip_rows,
        "tip_paid_total": paid_total,
        "tip_pending_total": pending_total,
    }


def _clip_post_close_value(value: str, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def build_post_close_status_embed(
    ticket_channel_id: int | str,
    customer_id: int | str,
) -> discord.Embed:
    status = get_post_close_status(ticket_channel_id, customer_id)
    targets = status["targets"]
    favorite_ids = set(status["favorite_ids"])
    tip_rows = status["tip_rows"]

    tips_by_staff: dict[str, list[sqlite3.Row]] = {}
    for row in tip_rows:
        staff_id = str(row["worker_discord_id"] or "")
        tips_by_staff.setdefault(staff_id, []).append(row)

    description_lines = [
        "這裡顯示本次服務的正式結果；操作與修改會在只有你看得到的面板中進行。"
    ]
    if status["skipped_all"]:
        description_lines.append("⏭️ 老闆已選擇不留評價。")

    embed = discord.Embed(
        title="本次服務紀錄",
        description="\n".join(description_lines),
        color=discord.Color.gold(),
    )

    if not targets:
        embed.add_field(
            name="服務成員",
            value="目前找不到接單成員資料。",
            inline=False,
        )
    else:
        for item in targets[:20]:
            staff_id = str(item.get("staff_id") or "")
            name = str(item.get("display_name") or staff_id or "成員")
            lines: list[str] = []

            if item.get("reviewed"):
                rating = int(item.get("rating") or 0)
                lines.append(f"⭐ **評星**｜{'⭐' * rating}（{rating}/5）")
                comment = str(item.get("comment") or "").strip()
                lines.append(
                    "💬 **評價**｜"
                    + (_clip_post_close_value(comment, 420) if comment else "未填寫文字評價")
                )
            elif status["skipped_all"]:
                lines.append("⭐ **評星**｜已略過")
                lines.append("💬 **評價**｜已選擇不留評價")
            else:
                lines.append("⭐ **評星**｜尚未評價")
                lines.append("💬 **評價**｜尚未填寫")

            staff_tips = tips_by_staff.get(staff_id, [])
            if staff_tips:
                tip_parts: list[str] = []
                for row in staff_tips:
                    amount = int(row["amount"] or 0)
                    tip_status = str(row["payment_status"] or "")
                    if tip_status == "paid":
                        label = "✅ 已付款"
                    elif tip_status == "pending_review":
                        label = "⏳ 待客服確認"
                    else:
                        label = "⏳ 處理中"
                    tip_parts.append(f"{amount:,}T {label}")
                lines.append("🍗 **雞腿**｜" + "、".join(tip_parts))
            else:
                lines.append("🍗 **雞腿**｜尚未加")

            lines.append(
                "❤️ **收藏**｜"
                + ("已收藏" if staff_id in favorite_ids else "尚未收藏")
            )

            embed.add_field(
                name=name,
                value=_clip_post_close_value("\n".join(lines)),
                inline=False,
            )

    paid_total = int(status["tip_paid_total"] or 0)
    pending_total = int(status["tip_pending_total"] or 0)
    if paid_total or pending_total:
        totals: list[str] = []
        if paid_total:
            totals.append(f"已付款 {paid_total:,}T")
        if pending_total:
            totals.append(f"待確認 {pending_total:,}T")
        embed.add_field(
            name="雞腿總覽",
            value="｜".join(totals),
            inline=False,
        )

    embed.set_footer(text="公開 Embed = 正式結果｜私人面板 = 選擇、預覽與修改")
    return embed

def _is_post_close_panel_message(message: discord.Message) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == "review_leave_button":
                return True
    return False


async def refresh_post_close_panel(
    channel: discord.TextChannel | None,
    customer_id: int | str,
) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        panel_message = None
        async for message in channel.history(limit=100):
            if _is_post_close_panel_message(message):
                panel_message = message
                break

        if panel_message is None:
            return False

        await panel_message.edit(
            embed=build_post_close_status_embed(
                channel.id,
                customer_id,
            )
        )
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return False
    except Exception as exc:
        print(
            f"[post-close-status] refresh failed "
            f"ticket_channel_id={channel.id}: {type(exc).__name__}: {exc}"
        )
        return False


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
    customer_name_public: bool,
    order_content: str | None,
) -> None:
    """評價只寫入網站 DB，不再轉發到 Discord 評價頻道。

    舊的 REVIEW_CHANNEL_ID 保留給相容設定用，但這裡不再發訊息，
    之後刪除舊評價頻道也不會影響結單後評價流程。
    """
    return


def _review_draft_preview(
    *,
    target: dict,
    rating: int,
    comment: str,
    customer_name_public: bool,
) -> str:
    name = str(target.get("display_name") or target.get("staff_id") or "成員")
    comment_text = str(comment or "").strip() or "未填寫文字評價"
    privacy = "公開老闆姓名" if customer_name_public else "匿名"
    return (
        f"**評價預覽｜{name}**\n\n"
        f"⭐ 評星：**{rating}/5**\n"
        f"💬 評價：{comment_text}\n"
        f"👤 顯示方式：{privacy}\n\n"
        "確認後才會正式寫入評價並更新公開 Embed。"
    )


class ReviewDraftConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        order_content: str | None,
        target: dict,
        customer_display_name: str,
        customer_name_public: bool,
        rating: int,
        comment: str,
    ):
        super().__init__(timeout=900)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.order_content = order_content
        self.target = dict(target)
        self.customer_display_name = str(customer_display_name or customer_id)
        self.customer_name_public = bool(customer_name_public)
        self.rating = int(rating)
        self.comment = str(comment or "")

    def preview_text(self) -> str:
        return _review_draft_preview(
            target=self.target,
            rating=self.rating,
            comment=self.comment,
            customer_name_public=self.customer_name_public,
        )

    @discord.ui.button(
        label="確認送出",
        style=discord.ButtonStyle.success,
        custom_id="review_draft_confirm",
        row=0,
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以送出評價。",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True,
            )
            return

        order, _targets = get_review_targets(self.ticket_channel_id)
        ok, message = record_member_review(
            order=order,
            ticket_channel_id=self.ticket_channel_id,
            staff_id=str(self.target.get("staff_id") or ""),
            staff_display_name=str(
                self.target.get("display_name")
                or self.target.get("staff_id")
                or ""
            ),
            customer_id=self.customer_id,
            customer_display_name=self.customer_display_name,
            customer_name_public=self.customer_name_public,
            rating=self.rating,
            comment=self.comment,
            order_content=self.order_content,
        )

        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return

        await interaction.response.defer()

        await refresh_staff_profile_panel_for_staff(
            guild,
            str(self.target.get("staff_id") or ""),
            reason="review_submitted",
        )

        await _send_review_channel_embed(
            guild=guild,
            customer_id=self.customer_id,
            target=self.target,
            rating=self.rating,
            comment=self.comment,
            customer_name_public=self.customer_name_public,
            order_content=self.order_content,
        )

        _order, statuses, _skipped_all = build_review_status(
            self.ticket_channel_id,
            self.customer_id,
        )
        all_done = bool(statuses) and all(
            bool(item.get("reviewed"))
            for item in statuses
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
            )

        try:
            if all_done:
                await interaction.delete_original_response()
            else:
                lines = ["請選擇下一位要評價的成員：", ""]
                for item in statuses:
                    state = (
                        f"已評價 ⭐ {item['rating']}"
                        if item.get("reviewed")
                        else "尚未評價"
                    )
                    lines.append(f"{_target_label(item)}｜{state}")

                await interaction.edit_original_response(
                    content="\n".join(lines),
                    view=MemberReviewMenuView(
                        customer_id=self.customer_id,
                        ticket_channel_id=self.ticket_channel_id,
                        order_content=self.order_content,
                    ),
                )
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(
        label="修改",
        style=discord.ButtonStyle.secondary,
        custom_id="review_draft_edit",
        row=0,
    )
    async def modify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以修改評價。",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            ReviewDraftEditModal(draft_view=self)
        )


class ReviewDraftEditModal(discord.ui.Modal, title="修改評價預覽"):
    def __init__(self, *, draft_view: ReviewDraftConfirmView):
        super().__init__(timeout=600)
        self.draft_view = draft_view

        self.rating_input = discord.ui.TextInput(
            label="星等",
            default=str(draft_view.rating),
            placeholder="請輸入 1～5",
            required=True,
            max_length=1,
        )
        self.comment_input = discord.ui.TextInput(
            label="評語",
            default=str(draft_view.comment or ""),
            placeholder="可空白；例如：報點清楚、很穩、很有耐心",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.public_input = discord.ui.TextInput(
            label="是否公開老闆姓名",
            default="是" if draft_view.customer_name_public else "否",
            placeholder="輸入「是」才顯示姓名；否則匿名",
            required=False,
            max_length=10,
        )
        self.add_item(self.rating_input)
        self.add_item(self.comment_input)
        self.add_item(self.public_input)

    async def on_submit(self, interaction: discord.Interaction):
        rating_number, _stars = rating_to_stars(self.rating_input.value)
        if rating_number is None:
            await interaction.response.send_message(
                "星等請輸入 1～5 的數字。",
                ephemeral=True,
            )
            return

        self.draft_view.rating = int(rating_number)
        self.draft_view.comment = str(self.comment_input.value or "")
        self.draft_view.customer_name_public = (
            interaction.user.id == self.draft_view.customer_id
            and is_customer_name_public_answer(self.public_input.value)
        )

        await interaction.response.edit_message(
            content=self.draft_view.preview_text(),
            view=self.draft_view,
        )


class MemberReviewModal(discord.ui.Modal, title="評價指定成員｜先預覽再送出"):
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
    customer_name_public_answer = discord.ui.TextInput(
        label="是否公開老闆姓名",
        placeholder="輸入「是」才顯示姓名；空白或「否」=匿名",
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
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以留下評價。",
                ephemeral=True,
            )
            return

        rating_number, _stars = rating_to_stars(self.rating.value)
        if rating_number is None:
            await interaction.response.send_message(
                "星等請輸入 1～5 的數字。",
                ephemeral=True,
            )
            return

        order, _targets = get_review_targets(self.ticket_channel_id)
        order_customer_display_name = (
            str(order["customer_display_name"] or "").strip()
            if order is not None and "customer_display_name" in order.keys()
            else ""
        )
        customer_display_name = str(
            order_customer_display_name
            or getattr(interaction.user, "display_name", None)
            or getattr(interaction.user, "name", None)
            or self.customer_id
        ).strip()

        customer_name_public = (
            interaction.user.id == self.customer_id
            and is_customer_name_public_answer(
                self.customer_name_public_answer.value
            )
        )

        preview_view = ReviewDraftConfirmView(
            customer_id=self.customer_id,
            ticket_channel_id=self.ticket_channel_id,
            order_content=self.order_content,
            target=self.target,
            customer_display_name=customer_display_name,
            customer_name_public=customer_name_public,
            rating=int(rating_number),
            comment=str(self.comment.value or ""),
        )

        await interaction.response.edit_message(
            content=preview_view.preview_text(),
            view=preview_view,
        )


def _worker_tip_row(tip_id: int) -> sqlite3.Row | None:
    ensure_review_tables()
    conn = _connect()
    try:
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def create_worker_tip(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str,
    customer_id: int,
    customer_display_name: str,
    target: dict,
    amount: int,
    payment_method: str,
    payment_status: str = "pending",
) -> int:
    ensure_review_tables()

    amount = int(amount)
    if amount <= 0:
        raise ValueError("雞腿金額必須大於 0。")

    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None
    dispatch_message_id = (
        str(order["dispatch_message_id"])
        if order is not None and order["dispatch_message_id"] is not None
        else None
    )
    receipt_id = (
        str(order["bot_order_no"])
        if order is not None and order["bot_order_no"] is not None
        else None
    )

    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO worker_tips (
                order_id,
                ticket_channel_id,
                dispatch_message_id,
                receipt_id,
                customer_discord_id,
                customer_display_name,
                worker_discord_id,
                worker_display_name,
                amount,
                payment_method,
                payment_status,
                payout_status,
                source,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unpaid', 'discord', ?, ?)
            """,
            (
                order_id,
                str(ticket_channel_id),
                dispatch_message_id,
                receipt_id,
                str(customer_id),
                str(customer_display_name or customer_id),
                str(target.get("staff_id") or ""),
                str(target.get("display_name") or target.get("staff_id") or ""),
                amount,
                str(payment_method),
                str(payment_status),
                now,
                now,
            ),
        )
        tip_id = int(cur.lastrowid)
        conn.commit()
        return tip_id
    finally:
        conn.close()


def set_worker_tip_confirmation_message(tip_id: int, message_id: int | str) -> None:
    ensure_review_tables()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE worker_tips
            SET confirmation_message_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (str(message_id), _now_iso(), int(tip_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_worker_tip_paid(
    tip_id: int,
    *,
    confirmed_by=None,
    wallet_transaction_id: int | None = None,
) -> sqlite3.Row | None:
    ensure_review_tables()
    now = _now_iso()
    confirmer_id = str(getattr(confirmed_by, "id", "") or "") or None
    confirmer_name = (
        getattr(confirmed_by, "display_name", None)
        or getattr(confirmed_by, "name", None)
        or confirmer_id
    )

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()

        if row is None:
            return None

        if str(row["payment_status"] or "") == "paid":
            return row

        if str(row["payment_status"] or "") == "cancelled":
            raise ValueError("這筆雞腿已取消，不能再確認付款。")

        conn.execute(
            """
            UPDATE worker_tips
            SET payment_status = 'paid',
                payout_status = CASE
                    WHEN payout_status = 'paid' THEN 'paid'
                    ELSE 'unpaid'
                END,
                wallet_transaction_id = COALESCE(?, wallet_transaction_id),
                confirmed_by_discord_id = COALESCE(?, confirmed_by_discord_id),
                confirmed_by_display_name = COALESCE(?, confirmed_by_display_name),
                paid_at = COALESCE(paid_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (
                wallet_transaction_id,
                confirmer_id,
                confirmer_name,
                now,
                now,
                int(tip_id),
            ),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def mark_worker_tip_cancelled(tip_id: int, *, cancelled_by=None) -> sqlite3.Row | None:
    ensure_review_tables()
    now = _now_iso()
    actor_name = (
        getattr(cancelled_by, "display_name", None)
        or getattr(cancelled_by, "name", None)
        or str(getattr(cancelled_by, "id", "") or "")
    )

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()

        if row is None:
            return None

        if str(row["payment_status"] or "") == "paid":
            raise ValueError("這筆雞腿已確認付款，不能直接取消。")

        conn.execute(
            """
            UPDATE worker_tips
            SET payment_status = 'cancelled',
                cancelled_at = ?,
                note = CASE
                    WHEN COALESCE(note, '') = '' THEN ?
                    ELSE note || '｜' || ?
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                f"由 {actor_name or '使用者'} 取消",
                f"由 {actor_name or '使用者'} 取消",
                now,
                int(tip_id),
            ),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def has_pending_worker_tips(ticket_channel_id: int | str) -> bool:
    ensure_review_tables()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM worker_tips
            WHERE ticket_channel_id = ?
              AND payment_status IN ('pending', 'pending_review')
            LIMIT 1
            """,
            (str(ticket_channel_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_pending_worker_tip_confirmations() -> list[dict]:
    ensure_review_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, customer_discord_id, confirmation_message_id
            FROM worker_tips
            WHERE payment_status = 'pending'
              AND confirmation_message_id IS NOT NULL
              AND TRIM(confirmation_message_id) <> ''
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


async def _log_worker_tip(event: str, *, interaction: discord.Interaction, tip_row: sqlite3.Row | None) -> None:
    callback = _WORKER_TIP_LOG_HANDLER
    if callback is None or tip_row is None:
        return

    try:
        await callback(
            event=event,
            interaction=interaction,
            tip=dict(tip_row),
        )
    except Exception as exc:
        print(f"[worker-tip] log callback failed tip_id={tip_row['id']}: {exc}")


async def _notify_worker_tip_paid(interaction: discord.Interaction, tip_row: sqlite3.Row | None) -> None:
    if tip_row is None:
        return

    guild = interaction.guild
    if guild is None:
        return

    try:
        worker_id = int(str(tip_row["worker_discord_id"] or "0"))
    except (TypeError, ValueError):
        worker_id = 0

    worker = guild.get_member(worker_id) if worker_id else None
    amount = int(tip_row["amount"] or 0)
    customer_name = str(tip_row["customer_display_name"] or tip_row["customer_discord_id"] or "老闆")

    if worker is not None:
        try:
            await worker.send(
                f"🍗 你收到 {customer_name} 的雞腿 {amount:,}T！\n"
                "此筆雞腿 100% 歸你，已列入獨立薪資紀錄。"
            )
        except discord.HTTPException:
            pass


def _worker_tip_preview_text(*, target: dict, amount: int) -> str:
    return (
        f"{WORKER_TIP_POLICY_TEXT}\n\n"
        f"指定成員：**{target.get('display_name') or target.get('staff_id')}**\n"
        f"雞腿金額：**{int(amount):,}T**\n\n"
        "確認金額後，請選擇付款方式；付款前仍可修改金額。"
    )


class WorkerTipAmountEditModal(discord.ui.Modal, title="修改雞腿金額"):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        target: dict,
        amount: int,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount_input = discord.ui.TextInput(
            label="雞腿金額",
            default=str(int(amount)),
            placeholder="請輸入正整數，例如：100、500、1000",
            required=True,
            min_length=1,
            max_length=9,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以修改雞腿金額。",
                ephemeral=True,
            )
            return

        raw = str(self.amount_input.value or "").strip().replace(",", "")
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "雞腿金額必須是大於 0 的正整數。",
                ephemeral=True,
            )
            return

        amount = int(raw)
        await interaction.response.edit_message(
            content=_worker_tip_preview_text(
                target=self.target,
                amount=amount,
            ),
            view=WorkerTipPaymentMethodView(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=amount,
            ),
        )


class WorkerTipAmountModal(discord.ui.Modal, title="🍗 加雞腿"):
    amount = discord.ui.TextInput(
        label="雞腿金額",
        placeholder="請輸入正整數，例如：100、500、1000",
        required=True,
        min_length=1,
        max_length=9,
    )

    def __init__(self, *, customer_id: int, ticket_channel_id: int, target: dict):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以加雞腿。",
                ephemeral=True,
            )
            return

        raw = str(self.amount.value or "").strip().replace(",", "")
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "雞腿金額必須是大於 0 的正整數。",
                ephemeral=True,
            )
            return

        amount = int(raw)
        await interaction.response.edit_message(
            content=_worker_tip_preview_text(
                target=self.target,
                amount=amount,
            ),
            view=WorkerTipPaymentMethodView(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=amount,
            ),
        )


class WorkerTipMemberSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, targets: list[dict]):
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.targets = [dict(item) for item in targets]

        options = []
        for target in self.targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue
            options.append(
                discord.SelectOption(
                    label=str(target.get("display_name") or staff_id)[:80],
                    value=staff_id,
                    description="選擇後輸入雞腿金額",
                    emoji="🍗",
                )
            )

        super().__init__(
            placeholder="選擇要加雞腿的成員",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以加雞腿。", ephemeral=True)
            return

        staff_id = str(self.values[0])
        target = next(
            (item for item in self.targets if str(item.get("staff_id") or "") == staff_id),
            None,
        )

        if target is None:
            await interaction.response.send_message("找不到這位成員，請重新打開加雞腿面板。", ephemeral=True)
            return

        await interaction.response.send_modal(
            WorkerTipAmountModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=target,
            )
        )


class WorkerTipMemberMenuView(discord.ui.View):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, targets: list[dict]):
        super().__init__(timeout=900)
        if targets:
            self.add_item(
                WorkerTipMemberSelect(
                    customer_id=customer_id,
                    ticket_channel_id=ticket_channel_id,
                    targets=targets,
                )
            )


class WorkerTipPaymentMethodSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, target: dict, amount: int):
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount = int(amount)
        self.processed = False

        super().__init__(
            placeholder="選擇雞腿付款方式",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="我的錢包", value="我的錢包", emoji="👛"),
                discord.SelectOption(label="街口", value="街口", emoji="💳"),
                discord.SelectOption(label="轉帳", value="轉帳", emoji="🏦"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以操作雞腿付款。", ephemeral=True)
            return

        if self.processed:
            await interaction.response.send_message("這次雞腿付款已經處理過了。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or channel.id != self.ticket_channel_id:
            await interaction.response.send_message("找不到原本的訂單票口，請重新操作。", ephemeral=True)
            return

        payment_method = str(self.values[0])
        order, _targets = get_review_targets(channel.id)

        if order is None:
            await interaction.response.send_message("找不到這張已結單訂單資料，暫時無法加雞腿。", ephemeral=True)
            return

        self.processed = True
        await interaction.response.defer(ephemeral=True)

        customer_name = (
            getattr(interaction.user, "display_name", None)
            or getattr(interaction.user, "name", None)
            or str(self.customer_id)
        )

        tip_id = create_worker_tip(
            order=order,
            ticket_channel_id=channel.id,
            customer_id=self.customer_id,
            customer_display_name=customer_name,
            target=self.target,
            amount=self.amount,
            payment_method=payment_method,
            payment_status=(
                "pending"
                if payment_method == "我的錢包"
                else "pending_review"
            ),
        )

        if payment_method == "我的錢包":
            handler = _WORKER_TIP_WALLET_HANDLER

            if handler is None:
                mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
                await interaction.followup.send(
                    "錢包付款系統尚未初始化，這筆雞腿沒有扣款，請稍後再試。",
                    ephemeral=True,
                )
                return

            base_order_no = str(order["bot_order_no"] or f"WEB-{order['id']}")
            wallet_reference = f"{base_order_no}:TIP-{tip_id}"

            try:
                tx = await handler(
                    customer_id=self.customer_id,
                    amount=self.amount,
                    order_channel_id=channel.id,
                    order_no=wallet_reference,
                    worker_id=str(self.target.get("staff_id") or ""),
                    worker_name=str(self.target.get("display_name") or self.target.get("staff_id") or ""),
                    operator=interaction.user,
                )
            except Exception as exc:
                mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
                error_text = str(exc).strip()
                if "duplicate wallet transaction reference" in error_text.lower():
                    error_text = (
                        "雞腿付款未完成：系統偵測到重複交易，"
                        "本次操作已取消且不會重複扣款。請重新開啟「加雞腿」再試一次。"
                    )
                elif not error_text:
                    error_text = "雞腿付款失敗，這筆雞腿沒有扣款，請重新操作。"

                await interaction.followup.send(error_text, ephemeral=True)
                return

            tip_row = mark_worker_tip_paid(
                tip_id,
                confirmed_by=interaction.user,
                wallet_transaction_id=int(tx.get("id") or 0) or None,
            )

            await channel.send(
                (
                    f"🍗 {interaction.user.mention} 給 "
                    f"<@{self.target.get('staff_id')}> 加了 **{self.amount:,}T** 雞腿！\n"
                    "此筆雞腿 100% 給指定成員，已由「我的錢包」完成付款。"
                ),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            await _notify_worker_tip_paid(interaction, tip_row)
            await _log_worker_tip("paid", interaction=interaction, tip_row=tip_row)

            await refresh_post_close_panel(channel, self.customer_id)

            # 已付款會直接顯示在公開 Embed；把付款方式選單收掉即可。
            try:
                await interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
            return

        try:
            from services.payment_reviews import (
                create_payment_review,
                set_payment_review_notification,
            )

            review = create_payment_review(
                source_type="worker_tip",
                source_id=tip_id,
                ticket_channel_id=channel.id,
                customer_discord_id=self.customer_id,
                customer_display_name=customer_name,
                target_discord_id=str(self.target.get("staff_id") or ""),
                target_display_name=str(
                    self.target.get("display_name")
                    or self.target.get("staff_id")
                    or ""
                ),
                amount=self.amount,
                payment_method=payment_method,
            )
        except Exception as exc:
            mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
            await interaction.followup.send(
                f"建立雞腿付款審核失敗：{exc}",
                ephemeral=True,
            )
            return

        review_message = await channel.send(
            (
                f"🍗 **雞腿付款已送出網站審核**\n"
                f"老闆：{interaction.user.mention}\n"
                f"指定成員：<@{self.target.get('staff_id')}>\n"
                f"金額：**{self.amount:,}T**\n"
                f"付款方式：**{payment_method}**\n\n"
                "雞腿 100% 給指定成員；不計原單抽成、不影響原訂單金額，"
                "也不列入 VIP 累積或會員點數。\n\n"
                "📎 **請將轉帳／街口付款截圖直接傳在此票口**，"
                "方便客服核對後到網站完成付款審核。\n"
                "客服確認前，這筆雞腿不會列入打手薪資。"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        set_worker_tip_confirmation_message(tip_id, review_message.id)

        try:
            set_payment_review_notification(
                int(review["id"]),
                review_message.id,
            )
        except Exception:
            pass

        tip_row = _worker_tip_row(tip_id)
        await _log_worker_tip("pending", interaction=interaction, tip_row=tip_row)

        # 這是仍需要使用者下一步動作的提示，因此保留；
        # 直接取代原付款方式選單，避免再多生一則私人訊息。
        await interaction.edit_original_response(
            content=(
                f"已建立 **{self.amount:,}T** 雞腿並送出網站審核。\n"
                "請把付款截圖貼在這個票口，等待客服確認。"
            ),
            view=None,
        )
        await refresh_post_close_panel(channel, self.customer_id)


class WorkerTipPaymentMethodView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        target: dict,
        amount: int,
    ):
        super().__init__(timeout=600)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount = int(amount)
        self.add_item(
            WorkerTipPaymentMethodSelect(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=self.amount,
            )
        )

    @discord.ui.button(
        label="修改金額",
        style=discord.ButtonStyle.secondary,
        custom_id="worker_tip_edit_amount",
        row=1,
    )
    async def modify_amount(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以修改雞腿金額。",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            WorkerTipAmountEditModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=self.amount,
            )
        )


class WorkerTipPaymentConfirmView(discord.ui.View):
    def __init__(self, *, tip_id: int, customer_id: int):
        super().__init__(timeout=None)
        self.tip_id = int(tip_id)
        self.customer_id = int(customer_id)

    @discord.ui.button(
        label="客服確認已收款",
        style=discord.ButtonStyle.success,
        custom_id="worker_tip_confirm_paid",
    )
    async def confirm_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以確認雞腿款項。", ephemeral=True)
            return

        tip_row = _worker_tip_row(self.tip_id)
        if tip_row is None:
            await interaction.response.send_message("找不到這筆雞腿紀錄。", ephemeral=True)
            return

        if str(tip_row["payment_status"] or "") == "paid":
            await interaction.response.send_message("這筆雞腿已經確認付款。", ephemeral=True)
            return

        if str(tip_row["payment_status"] or "") == "cancelled":
            await interaction.response.send_message("這筆雞腿已取消。", ephemeral=True)
            return

        try:
            tip_row = mark_worker_tip_paid(self.tip_id, confirmed_by=interaction.user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.edit_message(
            content=(
                "✅ **雞腿款項已確認**\n"
                f"老闆：<@{tip_row['customer_discord_id']}>\n"
                f"指定成員：<@{tip_row['worker_discord_id']}>\n"
                f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
                f"付款方式：**{tip_row['payment_method']}**\n"
                f"確認客服：{interaction.user.mention}\n\n"
                "此筆已列入指定成員的獨立雞腿薪資。"
            ),
            view=None,
        )
        await _notify_worker_tip_paid(interaction, tip_row)
        await _log_worker_tip("paid", interaction=interaction, tip_row=tip_row)
        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
            )

    @discord.ui.button(
        label="取消雞腿",
        style=discord.ButtonStyle.danger,
        custom_id="worker_tip_cancel_pending",
    )
    async def cancel_tip(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張單的老闆或客服可以取消待確認雞腿。", ephemeral=True)
            return

        try:
            tip_row = mark_worker_tip_cancelled(self.tip_id, cancelled_by=interaction.user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if tip_row is None:
            await interaction.response.send_message("找不到這筆雞腿紀錄。", ephemeral=True)
            return

        await interaction.response.edit_message(
            content=(
                "❌ **雞腿已取消**\n"
                f"老闆：<@{tip_row['customer_discord_id']}>\n"
                f"指定成員：<@{tip_row['worker_discord_id']}>\n"
                f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
                f"原付款方式：**{tip_row['payment_method']}**"
            ),
            view=None,
        )
        await _log_worker_tip("cancelled", interaction=interaction, tip_row=tip_row)
        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
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

        await interaction.response.defer()

        selected_ids = {str(value) for value in self.values}

        for target in self.targets:
            staff_id = str(target.get("staff_id") or "")
            if staff_id not in selected_ids:
                continue

            display_name = str(target.get("display_name") or staff_id)
            add_staff_favorite(
                customer_id=self.customer_id,
                staff_id=staff_id,
                staff_display_name=display_name,
                source="post_close",
            )

        guild = interaction.guild
        if guild is not None:
            for staff_id in selected_ids:
                await refresh_staff_profile_panel_for_staff(
                    guild,
                    staff_id,
                    reason="post_close_favorite",
                )

        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
            )

        # 收藏結果已反映在公開 Embed，收掉私人收藏選單。
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException):
            pass


class FavoriteCurrentMembersView(discord.ui.View):
    def __init__(self, *, customer_id: int, targets: list[dict]):
        super().__init__(timeout=300)
        self.customer_id = customer_id
        self.targets = targets

        if targets:
            self.add_item(FavoriteCurrentMembersSelect(customer_id=customer_id, targets=targets))


def _taipei_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(tz=ZoneInfo("Asia/Taipei"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        current = current.astimezone(ZoneInfo("Asia/Taipei"))
    return current.isoformat(timespec="seconds")


async def archive_ticket_channel(
    channel: discord.TextChannel,
    *,
    customer_id: int,
    closed_by: discord.Member | discord.User,
) -> int:
    order, _targets = get_review_targets(channel.id)

    customer_member = channel.guild.get_member(int(customer_id))
    customer_name = (
        str(order["customer_display_name"] or "").strip()
        if order is not None and "customer_display_name" in order.keys()
        else ""
    )
    if not customer_name:
        customer_name = str(
            getattr(customer_member, "display_name", None)
            or getattr(customer_member, "name", None)
            or customer_id
        )

    cs_id = ""
    cs_name = ""
    if order is not None:
        if "customer_service_discord_id" in order.keys():
            cs_id = str(order["customer_service_discord_id"] or "").strip()
        if "customer_service_display_name" in order.keys():
            cs_name = str(order["customer_service_display_name"] or "").strip()

    if not cs_id and isinstance(closed_by, discord.Member) and is_customer_staff(closed_by):
        cs_id = str(closed_by.id)
        cs_name = str(
            getattr(closed_by, "display_name", None)
            or getattr(closed_by, "name", None)
            or closed_by.id
        )

    messages: list[dict] = []
    async for message in channel.history(limit=None, oldest_first=True):
        attachments = [
            {
                "filename": str(attachment.filename or "附件"),
                "url": str(attachment.url),
                "content_type": str(attachment.content_type or ""),
                "size": int(attachment.size or 0),
            }
            for attachment in message.attachments
        ]

        embeds = []
        for embed in message.embeds:
            try:
                embeds.append(embed.to_dict())
            except Exception:
                continue

        messages.append(
            {
                "discord_message_id": str(message.id),
                "author_discord_id": str(getattr(message.author, "id", "") or ""),
                "author_display_name": str(
                    getattr(message.author, "display_name", None)
                    or getattr(message.author, "global_name", None)
                    or getattr(message.author, "name", None)
                    or getattr(message.author, "id", "未知使用者")
                ),
                "author_is_bot": bool(getattr(message.author, "bot", False)),
                "content": str(message.content or ""),
                "attachments": attachments,
                "embeds": embeds,
                "reply_to_message_id": str(
                    getattr(getattr(message, "reference", None), "message_id", "")
                    or ""
                ),
                "created_at": _taipei_iso(message.created_at),
                "edited_at": (
                    _taipei_iso(message.edited_at)
                    if message.edited_at is not None
                    else ""
                ),
            }
        )

    now_text = _taipei_iso()
    order_id = int(order["id"]) if order is not None else None
    order_no = (
        str(order["bot_order_no"] or "").strip()
        if order is not None and "bot_order_no" in order.keys()
        else ""
    )

    return save_ticket_archive(
        ticket_channel_id=channel.id,
        ticket_channel_name=channel.name,
        order_id=order_id,
        order_no=order_no,
        customer_discord_id=customer_id,
        customer_display_name=customer_name,
        customer_service_discord_id=cs_id,
        customer_service_display_name=cs_name,
        closed_by_discord_id=getattr(closed_by, "id", ""),
        closed_by_display_name=str(
            getattr(closed_by, "display_name", None)
            or getattr(closed_by, "name", None)
            or getattr(closed_by, "id", "未知")
        ),
        closed_at=now_text,
        archived_at=now_text,
        messages=messages,
    )


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

        if has_pending_worker_tips(channel.id):
            await interaction.response.send_message(
                "這張票口還有待客服確認的雞腿款項。請先完成確認或取消雞腿，再關閉票口。",
                ephemeral=True,
            )
            return

        # 關閉前一定先封存；封存失敗就保留票口，避免爭議紀錄一起消失。
        await interaction.response.defer(ephemeral=True)

        try:
            archive_id = await archive_ticket_channel(
                channel,
                customer_id=self.customer_id,
                closed_by=interaction.user,
            )
        except Exception as exc:
            print(
                f"[ticket-archive] failed channel_id={channel.id}: "
                f"{type(exc).__name__}: {exc}"
            )
            await interaction.followup.send(
                "票口聊天紀錄封存失敗，因此本次沒有刪除票口。請客服稍後重試。",
                ephemeral=True,
            )
            return

        try:
            await channel.send(
                (
                    f"{interaction.user.mention} 已確認關閉票口。"
                    f"聊天紀錄已封存（紀錄 #{archive_id}），頻道將在 3 秒後刪除。"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

        await asyncio.sleep(3)
        await channel.delete(
            reason=f"Closed post-order ticket by {interaction.user}"
        )

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
        label="🍗 加雞腿",
        style=discord.ButtonStyle.primary,
        custom_id="review_worker_tip_button",
        row=0,
    )
    async def add_worker_tip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以加雞腿。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        _order, targets = get_review_targets(channel.id)

        if not targets:
            await interaction.response.send_message(
                "這張單目前找不到接單成員資料，因此無法指定雞腿對象。請客服先確認網站接單資料。",
                ephemeral=True,
            )
            return

        lines = [
            WORKER_TIP_POLICY_TEXT,
            "",
            "**請從下拉清單選擇要加雞腿的成員：**",
        ]

        for item in targets:
            lines.append(f"• {_target_label(item)}")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
            view=WorkerTipMemberMenuView(
                customer_id=self.customer_id,
                ticket_channel_id=channel.id,
                targets=targets,
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

        # 不另外留下私人成功訊息；公開 Embed 會直接顯示「已選擇不留評價」。
        await interaction.response.defer()

        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        try:
            await channel.send(
                f"{interaction.user.mention} 已選擇不留評價。需要時可按「關閉票口」。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

        await refresh_post_close_panel(channel, self.customer_id)

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

        await interaction.response.defer(ephemeral=True)

        _order, targets = get_review_targets(channel.id)

        if not targets:
            await interaction.followup.send(
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

        await interaction.followup.send(
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
