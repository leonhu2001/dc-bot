from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord

TAIPEI_TZ = timezone(timedelta(hours=8))
VIP_EXPIRY_REMINDER_DAYS = 7


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bot.db"


def _db_path(db_file: str | Path | None = None) -> Path:
    return Path(db_file) if db_file is not None else _default_db_path()


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


def _format_date(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%Y/%m/%d") if parsed is not None else "—"


def ensure_vip_customer_notification_table(
    db_file: str | Path | None = None,
) -> None:
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vip_customer_retention_notifications (
                customer_id TEXT PRIMARY KEY,
                reminded_expiry_at TEXT,
                reminder_sent_at TEXT,
                resolved_expiry_at TEXT,
                resolved_sent_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _state_map(db_file: str | Path | None = None) -> dict[str, dict[str, Any]]:
    ensure_vip_customer_notification_table(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM vip_customer_retention_notifications"
        ).fetchall()
    return {str(row["customer_id"]): dict(row) for row in rows}


def list_expiry_reminders(
    rows: list[dict[str, Any]],
    *,
    reminder_days: int = VIP_EXPIRY_REMINDER_DAYS,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    states = _state_map(db_file)
    safe_days = max(1, int(reminder_days or VIP_EXPIRY_REMINDER_DAYS))
    result: list[dict[str, Any]] = []

    for row in rows:
        if int(row.get("current_index") or 0) <= 0 or bool(row.get("is_due")):
            continue
        expiry_at = str(row.get("expiry_at") or "").strip()
        if not expiry_at:
            continue
        try:
            days_remaining = int(row.get("days_remaining"))
        except (TypeError, ValueError):
            continue
        if days_remaining < 1 or days_remaining > safe_days:
            continue

        state = states.get(str(row.get("customer_id") or "")) or {}
        if str(state.get("reminded_expiry_at") or "") == expiry_at:
            continue
        result.append(row)

    return result


def mark_expiry_reminder_sent(
    row: dict[str, Any],
    *,
    db_file: str | Path | None = None,
) -> None:
    customer_id = str(row.get("customer_id") or "").strip()
    expiry_at = str(row.get("expiry_at") or "").strip()
    if not customer_id or not expiry_at:
        return

    ensure_vip_customer_notification_table(db_file)
    now_text = _now_iso()
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            INSERT INTO vip_customer_retention_notifications (
                customer_id,
                reminded_expiry_at,
                reminder_sent_at,
                resolved_expiry_at,
                resolved_sent_at,
                updated_at
            ) VALUES (?, ?, ?, NULL, NULL, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                reminded_expiry_at = excluded.reminded_expiry_at,
                reminder_sent_at = excluded.reminder_sent_at,
                resolved_expiry_at = NULL,
                resolved_sent_at = NULL,
                updated_at = excluded.updated_at
            """,
            (customer_id, expiry_at, now_text, now_text),
        )
        conn.commit()


def list_retention_renewals(
    rows: list[dict[str, Any]],
    *,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    states = _state_map(db_file)
    result: list[dict[str, Any]] = []

    for row in rows:
        if int(row.get("current_index") or 0) <= 0 or bool(row.get("is_due")):
            continue
        customer_id = str(row.get("customer_id") or "").strip()
        state = states.get(customer_id) or {}
        reminded_expiry = _parse_datetime(state.get("reminded_expiry_at"))
        current_expiry = _parse_datetime(row.get("expiry_at"))
        if reminded_expiry is None or current_expiry is None:
            continue
        if current_expiry <= reminded_expiry:
            continue
        if str(state.get("resolved_expiry_at") or "") == str(row.get("expiry_at") or ""):
            continue
        result.append(row)

    return result


def mark_retention_resolved(
    customer_id: str | int,
    expiry_at: Any,
    *,
    db_file: str | Path | None = None,
) -> None:
    customer_id_text = str(customer_id or "").strip()
    expiry_text = str(expiry_at or "").strip()
    if not customer_id_text or not expiry_text:
        return

    ensure_vip_customer_notification_table(db_file)
    now_text = _now_iso()
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            INSERT INTO vip_customer_retention_notifications (
                customer_id,
                reminded_expiry_at,
                reminder_sent_at,
                resolved_expiry_at,
                resolved_sent_at,
                updated_at
            ) VALUES (?, NULL, NULL, ?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                resolved_expiry_at = excluded.resolved_expiry_at,
                resolved_sent_at = excluded.resolved_sent_at,
                updated_at = excluded.updated_at
            """,
            (customer_id_text, expiry_text, now_text, now_text),
        )
        conn.commit()


async def _resolve_user(bot: discord.Client, customer_id: str | int):
    customer_id_text = str(customer_id or "").strip()
    if not customer_id_text.isdigit():
        return None
    user_id = int(customer_id_text)

    user = None
    try:
        user = bot.get_user(user_id)
    except Exception:
        user = None
    if user is not None:
        return user

    try:
        return await bot.fetch_user(user_id)
    except Exception:
        return None


async def _send_dm(
    bot: discord.Client,
    customer_id: str | int,
    *,
    embed: discord.Embed,
) -> bool:
    user = await _resolve_user(bot, customer_id)
    if user is None:
        print(f"[vip-customer] user not found user={customer_id}", flush=True)
        return False
    try:
        await user.send(embed=embed)
        return True
    except Exception as exc:
        print(
            f"[vip-customer] dm failed user={customer_id} error={type(exc).__name__}",
            flush=True,
        )
        return False


async def send_expiry_reminder(
    bot: discord.Client,
    row: dict[str, Any],
) -> bool:
    days = max(1, int(row.get("days_remaining") or 1))
    embed = discord.Embed(
        title="💎 VIP 保級提醒",
        description=(
            f"你的 **{row.get('current_level') or 'VIP'}** 保級期限將於 "
            f"**{_format_date(row.get('expiry_at'))}** 到期。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="剩餘時間", value=f"{days} 天", inline=True)
    embed.add_field(
        name="保級方式",
        value="期限前完成有效消費後，保級期限會重新計算。",
        inline=False,
    )
    return await _send_dm(bot, row.get("customer_id"), embed=embed)


async def send_retention_extended(
    bot: discord.Client,
    *,
    customer_id: str | int,
    level_name: str,
    expiry_at: Any,
) -> bool:
    embed = discord.Embed(
        title="✅ VIP 保級已延長",
        description=(
            f"你的 **{level_name or 'VIP'}** 保級期限已更新至 "
            f"**{_format_date(expiry_at)}**。"
        ),
        color=discord.Color.green(),
    )
    return await _send_dm(bot, customer_id, embed=embed)


async def send_level_changed(
    bot: discord.Client,
    *,
    customer_id: str | int,
    old_level: str,
    new_level: str,
) -> bool:
    embed = discord.Embed(
        title="💎 VIP 等級已更新",
        description=f"你的 VIP 等級已由 **{old_level}** 調整為 **{new_level}**。",
        color=discord.Color.purple(),
    )
    return await _send_dm(bot, customer_id, embed=embed)
