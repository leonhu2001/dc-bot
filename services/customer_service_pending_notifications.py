"""Discord客服頻道：內部薪資轉帳與付款審核待辦通知。

網站只負責寫入資料庫；Bot 定期讀取待審核資料並通知，避免網站請求
因 Discord API 暫時故障而被錯誤回滾。原票口的付款提示照常保留。
"""
from __future__ import annotations

import sqlite3
import traceback

import discord

from core.discord_settings import (
    CUSTOMER_SERVICE_REVIEW_CHANNEL_ID,
    CUSTOMER_SERVICE_ROLE_ID,
)
from services.payment_reviews import _db_path as payment_db_path, ensure_payment_review_tables
from services.cs_review_presentation import (
    REVIEW_ACTION_LABEL,
    review_embed_payload,
    review_notification_text,
)
from web.app.services import internal_transfers

PAYMENT_URL = "https://mowanentertainment.com/admin/payment-reviews?status=pending"
TRANSFER_URL = "https://mowanentertainment.com/employee/internal-transfers"
_PAYMENT_STATUS = {
    "pending_review": "待客服審核",
    "approved_pending_apply": "已核准，等待套用",
    "applied": "已完成",
    "rejected": "已駁回",
    "apply_error": "套用失敗，請客服處理",
}
_TRANSFER_STATUS = {
    "pending": "待客服審核",
    "approved": "已核准",
    "rejected": "已駁回",
    "cancelled": "已取消",
}


def _migrate_column(conn: sqlite3.Connection, table: str, name: str) -> None:
    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")


def _payment_connection() -> sqlite3.Connection:
    ensure_payment_review_tables()
    conn = sqlite3.connect(payment_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        _migrate_column(conn, "payment_reviews", "cs_notice_message_id")
        _migrate_column(conn, "payment_reviews", "cs_notice_resolved_at")
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def _transfer_connection() -> sqlite3.Connection:
    internal_transfers.ensure_internal_transfer_tables()
    conn = internal_transfers._connect()
    try:
        _migrate_column(conn, "employee_internal_transfers", "cs_notice_message_id")
        _migrate_column(conn, "employee_internal_transfers", "cs_notice_resolved_at")
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def _rows(connector, table: str, status: str) -> tuple[list[dict], list[dict]]:
    conn = connector()
    try:
        pending = conn.execute(
            f"SELECT * FROM {table} "
            "WHERE status = ? AND cs_notice_message_id IS NULL "
            "ORDER BY id ASC LIMIT 30",
            (status,),
        ).fetchall()
        resolved = conn.execute(
            f"SELECT * FROM {table} "
            "WHERE status != ? AND cs_notice_message_id IS NOT NULL "
            "AND cs_notice_resolved_at IS NULL "
            "ORDER BY id ASC LIMIT 30",
            (status,),
        ).fetchall()
        return [dict(row) for row in pending], [dict(row) for row in resolved]
    finally:
        conn.close()


def _mark(connector, table: str, row_id: int, *, message_id: int | None = None) -> None:
    conn = connector()
    try:
        if message_id is not None:
            conn.execute(
                f"UPDATE {table} SET cs_notice_message_id=? "
                "WHERE id=? AND cs_notice_message_id IS NULL",
                (str(message_id), row_id),
            )
        else:
            conn.execute(
                f"UPDATE {table} SET cs_notice_resolved_at=datetime('now') "
                "WHERE id=? AND cs_notice_resolved_at IS NULL",
                (row_id,),
            )
        conn.commit()
    finally:
        conn.close()


async def _get_channel(bot: discord.Client):
    channel = bot.get_channel(CUSTOMER_SERVICE_REVIEW_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(CUSTOMER_SERVICE_REVIEW_CHANNEL_ID)
    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError("客服審核頻道不存在或 Bot 無發言權限")
    return channel


def _payment_embed(row: dict, *, resolved: bool = False) -> discord.Embed:
    status = str(row.get("status") or "pending_review")
    extras = [
        ("來源", "雞腿" if row.get("source_type") == "worker_tip" else "訂單", True),
        ("付款方式", str(row.get("payment_method") or "未提供"), True),
    ]
    channel_id = str(row.get("ticket_channel_id") or "").strip()
    if channel_id.isdigit():
        extras.append((
            "付款票口",
            f"https://discord.com/channels/1129474191226306672/{channel_id}",
            False,
        ))
    return discord.Embed.from_dict(review_embed_payload(
        category="付款審核",
        status=status,
        status_label=_PAYMENT_STATUS.get(status, status),
        description=(
            "已完成狀態更新，請以網站後台紀錄為準。"
            if resolved else "請核對付款憑證與金額，再從網站後台審核。"
        ),
        reference=str(row.get("review_no") or row.get("id")),
        applicant=str(row.get("customer_display_name") or row.get("customer_discord_id") or "未知"),
        amount=int(row.get("amount") or 0),
        fields=extras,
    ))


def _transfer_embed(row: dict, *, resolved: bool = False) -> discord.Embed:
    status = str(row.get("status") or "pending")
    return discord.Embed.from_dict(review_embed_payload(
        category="內部轉帳",
        status=status,
        status_label=_TRANSFER_STATUS.get(status, status),
        description=(
            "此筆內部轉帳審核狀態已更新。"
            if resolved else "請確認轉出／轉入成員與金額，再從後台審核。"
        ),
        reference=f"#{row.get('id')}",
        applicant=str(row.get("created_by_display_name") or row.get("created_by_discord_id") or "未知"),
        amount=int(row.get("amount") or 0),
        fields=[
            ("轉出", str(row.get("from_employee_display_name") or row.get("from_employee_discord_id") or "未知"), True),
            ("轉入", str(row.get("to_employee_display_name") or row.get("to_employee_discord_id") or "未知"), True),
            ("原因", str(row.get("reason") or "未提供"), False),
        ],
    ))


async def _process_kind(bot, channel, *, connector, table: str, pending_status: str,
                        embed_builder, url: str, label: str) -> None:
    pending, resolved = _rows(connector, table, pending_status)
    for row in pending:
        try:
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label=REVIEW_ACTION_LABEL, url=url, style=discord.ButtonStyle.link))
            message = await channel.send(
                content=f"<@&{CUSTOMER_SERVICE_ROLE_ID}> {review_notification_text(label, reference=str(row.get('review_no') or row.get('id')))}",
                embed=embed_builder(row),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=False, roles=True, everyone=False),
            )
            _mark(connector, table, int(row["id"]), message_id=message.id)
        except Exception:
            print(f"[cs-review-alert] notify {table} id={row.get('id')} failed\n{traceback.format_exc()}", flush=True)
    for row in resolved:
        try:
            message = await channel.fetch_message(int(row["cs_notice_message_id"]))
            await message.edit(
                content=f"📋 {label}審核狀態已更新｜{str(row.get('review_no') or row.get('id'))}",
                embed=embed_builder(row, resolved=True),
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            _mark(connector, table, int(row["id"]))
        except discord.NotFound:
            # Notification may have been deleted by a moderator; don't retry endlessly.
            _mark(connector, table, int(row["id"]))
        except Exception:
            print(f"[cs-review-alert] update {table} id={row.get('id')} failed\n{traceback.format_exc()}", flush=True)


async def process_customer_service_pending_notifications(bot: discord.Client) -> None:
    """Called by the already-running payment-review worker every four seconds."""
    try:
        channel = await _get_channel(bot)
    except Exception:
        print(f"[cs-review-alert] customer service channel unavailable\n{traceback.format_exc()}", flush=True)
        return
    for connector, table, status, builder, url, label in (
        (_payment_connection, "payment_reviews", "pending_review", _payment_embed, PAYMENT_URL, "付款"),
        (_transfer_connection, "employee_internal_transfers", "pending", _transfer_embed, TRANSFER_URL, "內部轉帳"),
    ):
        try:
            await _process_kind(
                bot, channel, connector=connector, table=table, pending_status=status,
                embed_builder=builder, url=url, label=label,
            )
        except Exception:
            print(f"[cs-review-alert] processing {table} failed\n{traceback.format_exc()}", flush=True)
