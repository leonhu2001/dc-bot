import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

import discord

from core.time_utils import get_taipei_now
from services.orders import (
    get_order_amount_for_stats,
    is_closed_order_for_stats,
    is_stored_order_for_stats,
    is_cancelled_order_for_stats,
)
from services.rewards import format_t_amount

_DB_FILE: Path | None = None
_INIT_DATABASE: Callable[[], None] | None = None


def configure_stats(db_file: str | Path, init_database_func: Callable[[], None]) -> None:
    global _DB_FILE, _INIT_DATABASE
    _DB_FILE = Path(db_file)
    _INIT_DATABASE = init_database_func


def _get_db_file() -> Path:
    if _DB_FILE is None:
        raise RuntimeError("stats service 尚未設定 DB_FILE，請先呼叫 configure_stats()")
    return _DB_FILE


def _run_init_database() -> None:
    if _INIT_DATABASE is None:
        raise RuntimeError("stats service 尚未設定 init_database，請先呼叫 configure_stats()")
    _INIT_DATABASE()


def _parse_iso_datetime_safely(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt


def _get_order_closed_time(data: dict) -> datetime | None:
    return (
        _parse_iso_datetime_safely(data.get("closed_at"))
        or _parse_iso_datetime_safely(data.get("reward_counted_at"))
        or _parse_iso_datetime_safely(data.get("updated_at"))
    )


def _normalize_stats_datetime_text(value: str | None) -> str | None:
    if not value:
        return None
    dt = _parse_iso_datetime_safely(str(value))
    if dt is None:
        # 支援 YYYYMMDD 這種舊補登日期
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}T00:00:00+08:00"
        return None
    return dt.isoformat(timespec="seconds")


def _get_sales_stats_from_sqlite(start_dt: datetime, end_dt: datetime) -> tuple[int, int, int, int]:
    """直接從 SQLite 統計營收，並相容兩種資料：
    1. 目前 Bot 使用的 JSON blob orders.data
    2. 舊營業額補登用的 relational/manual_revenue 資料
    回傳：完成訂單數、營收、目前存單數、目前取消單數
    """
    _run_init_database()
    start_text = start_dt.isoformat(timespec="seconds")
    end_text = end_dt.isoformat(timespec="seconds")

    completed_count = 0
    total_revenue = 0
    stored_count = 0
    cancelled_count = 0

    try:
        with sqlite3.connect(_get_db_file()) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            table_names = {
                row[0]
                for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            if "orders" in table_names:
                order_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(orders)").fetchall()
                }

                # 新版 SQLite 過渡資料表：orders(channel_id, data, updated_at)
                if "data" in order_columns:
                    for row in cur.execute("SELECT data FROM orders").fetchall():
                        try:
                            data = json.loads(row["data"])
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(data, dict):
                            continue

                        if is_stored_order_for_stats(data):
                            stored_count += 1
                        if is_cancelled_order_for_stats(data):
                            cancelled_count += 1
                        if not is_closed_order_for_stats(data):
                            continue

                        closed_text = _normalize_stats_datetime_text(
                            data.get("closed_at") or data.get("reward_counted_at") or data.get("updated_at")
                        )
                        if closed_text is None or not (start_text <= closed_text < end_text):
                            continue

                        completed_count += 1
                        total_revenue += get_order_amount_for_stats(data)

                # 舊補登或正式 relational orders：orders(... amount/status/closed_at ...)
                if {"amount", "status"}.issubset(order_columns):
                    date_column = "closed_at" if "closed_at" in order_columns else "created_at"

                    if date_column in order_columns:
                        query = f"""
                            SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                            FROM orders
                            WHERE status = 'closed'
                              AND {date_column} >= ?
                              AND {date_column} < ?
                        """
                        row = cur.execute(query, (start_text, end_text)).fetchone()
                        completed_count += int(row["count_value"] or 0)
                        total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

            # 建議之後舊營業額統一補進 manual_revenue，避免跟正式 orders 混在一起。
            if "manual_revenue" in table_names:
                manual_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(manual_revenue)").fetchall()
                }
                if {"date_text", "amount", "status"}.issubset(manual_columns):
                    row = cur.execute(
                        """
                        SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                        FROM manual_revenue
                        WHERE status = 'closed'
                          AND date_text >= ?
                          AND date_text < ?
                        """,
                        (start_text[:10], end_text[:10]),
                    ).fetchone()
                    completed_count += int(row["count_value"] or 0)
                    total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

    except sqlite3.Error as e:
        print(f"讀取 SQLite 統計失敗：{e}")

    return completed_count, total_revenue, stored_count, cancelled_count


def build_sales_stats_embed(title: str, start_dt: datetime, end_dt: datetime) -> discord.Embed:
    completed_count, total_revenue, stored_count, cancelled_count = _get_sales_stats_from_sqlite(start_dt, end_dt)
    avg_order = total_revenue // completed_count if completed_count else 0

    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="完成訂單數", value=f"{completed_count:,} 單", inline=True)
    embed.add_field(name="營收", value=format_t_amount(total_revenue), inline=True)
    embed.add_field(name="平均客單價", value=format_t_amount(avg_order), inline=True)
    embed.add_field(name="目前存單數", value=f"{stored_count:,} 單", inline=True)
    embed.add_field(name="目前取消單數", value=f"{cancelled_count:,} 單", inline=True)
    embed.set_footer(text=f"統計區間：{start_dt.strftime('%Y/%m/%d %H:%M')} ～ {end_dt.strftime('%Y/%m/%d %H:%M')}")
    return embed
