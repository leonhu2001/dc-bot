from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path
from typing import Callable

import discord

from core.time_utils import get_taipei_now, get_taipei_now_iso

_DB_FILE: Path | None = None
_init_database: Callable[[], None] | None = None


def configure_lottery_storage(db_file: Path, init_database_func: Callable[[], None]) -> None:
    global _DB_FILE, _init_database
    _DB_FILE = Path(db_file)
    _init_database = init_database_func


def _ensure_configured() -> tuple[Path, Callable[[], None]]:
    if _DB_FILE is None or _init_database is None:
        raise RuntimeError("lottery storage is not configured")
    return _DB_FILE, _init_database


LOTTERY_COST_PER_CHANCE_DEFAULT = 5
LOTTERY_MAX_CHANCES_PER_USER_DEFAULT = 20


def get_default_lottery_period() -> str:
    return get_taipei_now().strftime("%Y-%m")


def get_lottery_settings() -> dict:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    default = {
        "period": get_default_lottery_period(),
        "title": "魔丸點數抽獎",
        "note": "獎品由管理層討論後設定。",
        "prizes": "獎池尚未設定，請等待管理層公告。",
        "status": "open",
        "cost_per_chance": LOTTERY_COST_PER_CHANCE_DEFAULT,
        "max_chances_per_user": LOTTERY_MAX_CHANCES_PER_USER_DEFAULT,
        "updated_at": get_taipei_now_iso(),
    }

    try:
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT data FROM lottery_settings WHERE key='current'").fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎設定失敗：{e}")
        return default

    if row is None:
        save_lottery_settings(default)
        return default

    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return default

    for key, value in default.items():
        data.setdefault(key, value)

    return data


def save_lottery_settings(data: dict) -> None:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    data["updated_at"] = get_taipei_now_iso()
    try:
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lottery_settings (key, data, updated_at) VALUES (?, ?, ?)",
                ("current", json.dumps(data, ensure_ascii=False), data["updated_at"]),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎設定失敗：{e}")


def get_lottery_entries(period: str) -> list[dict]:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    try:
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT user_id, chances, points_used, updated_at
                FROM lottery_entries
                WHERE period=? AND chances > 0
                ORDER BY chances DESC, updated_at ASC
                """,
                (period,),
            ).fetchall()
    except sqlite3.Error as e:
        print(f"讀取抽獎池失敗：{e}")
        return []

    return [
        {
            "user_id": int(row["user_id"]),
            "chances": int(row["chances"]),
            "points_used": int(row["points_used"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_lottery_entry(period: str, user_id: int) -> dict | None:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    try:
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, chances, points_used, updated_at FROM lottery_entries WHERE period=? AND user_id=?",
                (period, user_id),
            ).fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎報名資料失敗：{e}")
        return None

    if row is None:
        return None

    return {
        "user_id": int(row["user_id"]),
        "chances": int(row["chances"]),
        "points_used": int(row["points_used"]),
        "updated_at": row["updated_at"],
    }


def upsert_lottery_entry(period: str, user_id: int, chances_delta: int, points_delta: int) -> None:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    now_text = get_taipei_now_iso()
    current = get_lottery_entry(period, user_id)
    new_chances = chances_delta if current is None else int(current["chances"]) + chances_delta
    new_points_used = points_delta if current is None else int(current["points_used"]) + points_delta

    try:
        with sqlite3.connect(db_file) as conn:
            if new_chances <= 0:
                conn.execute("DELETE FROM lottery_entries WHERE period=? AND user_id=?", (period, user_id))
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lottery_entries (period, user_id, chances, points_used, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (period, user_id, new_chances, max(new_points_used, 0), now_text),
                )
            conn.commit()
    except sqlite3.Error as e:
        print(f"更新抽獎報名資料失敗：{e}")


def clear_lottery_entries(period: str) -> None:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    try:
        with sqlite3.connect(db_file) as conn:
            conn.execute("DELETE FROM lottery_entries WHERE period=?", (period,))
            conn.commit()
    except sqlite3.Error as e:
        print(f"清空抽獎池失敗：{e}")


def record_lottery_draw(period: str, prize: str, winner_id: int, drawn_by: int) -> None:
    db_file, _init_database_func = _ensure_configured()
    _init_database_func()
    try:
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """
                INSERT INTO lottery_draws (period, prize, winner_id, drawn_by, drawn_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (period, prize, winner_id, drawn_by, get_taipei_now_iso()),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎結果失敗：{e}")


def build_lottery_info_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)
    participant_count = len(entries)
    cost = int(settings.get("cost_per_chance", LOTTERY_COST_PER_CHANCE_DEFAULT))
    max_chances = int(settings.get("max_chances_per_user", LOTTERY_MAX_CHANCES_PER_USER_DEFAULT))
    status_text = "開放報名" if settings.get("status") == "open" else "已關閉"

    embed = discord.Embed(
        title=str(settings.get("title") or "魔丸點數抽獎"),
        color=discord.Color.gold(),
    )
    embed.add_field(name="本期", value=period, inline=True)
    embed.add_field(name="狀態", value=status_text, inline=True)
    embed.add_field(name="規則", value=f"{cost} 點 = 1 次抽獎機會\n每人本期最多 {max_chances} 次", inline=False)
    embed.add_field(name="目前抽獎池", value=f"參與人數：{participant_count} 人\n總抽獎次數：{total_chances} 次", inline=False)
    prizes = str(settings.get("prizes") or "獎池尚未設定，請等待管理層公告。")
    embed.add_field(name="獎池內容", value=prizes[:1000], inline=False)

    note = str(settings.get("note") or "獎品由管理層討論後設定。")
    embed.add_field(name="活動備註", value=note[:1000], inline=False)
    return embed


def build_lottery_status_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)

    embed = build_lottery_info_embed(settings)
    embed.title = f"抽獎池狀態｜{period}"

    if not entries:
        embed.add_field(name="參加名單", value="目前沒有人參加。", inline=False)
        return embed

    lines = []
    for index, row in enumerate(entries[:20], start=1):
        chance_rate = (int(row["chances"]) / total_chances * 100) if total_chances else 0
        lines.append(f"{index}. <@{row['user_id']}>｜{row['chances']} 次｜約 {chance_rate:.1f}%")

    if len(entries) > 20:
        lines.append(f"...另有 {len(entries) - 20} 人")

    embed.add_field(name="參加名單", value="\n".join(lines), inline=False)
    return embed


def pick_weighted_lottery_winners(entries: list[dict], winners: int) -> list[int]:
    pool = [dict(row) for row in entries if int(row.get("chances", 0)) > 0]
    picked: list[int] = []

    for _ in range(max(winners, 0)):
        if not pool:
            break

        total_weight = sum(int(row["chances"]) for row in pool)
        if total_weight <= 0:
            break

        ticket = random.randint(1, total_weight)
        running = 0
        chosen_index = 0

        for index, row in enumerate(pool):
            running += int(row["chances"])
            if ticket <= running:
                chosen_index = index
                break

        winner = pool.pop(chosen_index)
        picked.append(int(winner["user_id"]))

    return picked

