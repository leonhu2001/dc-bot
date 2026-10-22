from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from core.time_utils import get_taipei_now, get_taipei_now_iso


ROOT = Path(__file__).resolve().parents[3]
BOT_DB = ROOT / "bot.db"
_PERIOD_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(BOT_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_lottery_admin_tables() -> None:
    BOT_DB.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lottery_settings (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lottery_entries (
                period TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chances INTEGER NOT NULL DEFAULT 0,
                points_used INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (period, user_id)
            );

            CREATE TABLE IF NOT EXISTS lottery_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                prize TEXT NOT NULL,
                winner_id INTEGER NOT NULL,
                drawn_by INTEGER NOT NULL,
                drawn_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _default_settings() -> dict[str, Any]:
    return {
        "period": get_taipei_now().strftime("%Y-%m"),
        "title": "魔丸點數抽獎",
        "note": "獎品由管理層討論後設定。",
        "prizes": "獎池尚未設定，請等待管理層公告。",
        "status": "open",
        "cost_per_chance": 5,
        "max_chances_per_user": 20,
        "updated_at": get_taipei_now_iso(),
    }


def get_lottery_settings() -> dict[str, Any]:
    ensure_lottery_admin_tables()
    default = _default_settings()
    with _connect() as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM lottery_settings WHERE key='current'"
        ).fetchone()

    if row is None:
        return default

    try:
        data = json.loads(str(row["data"] or "{}"))
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key, value in default.items():
        data.setdefault(key, value)
    data["updated_at"] = str(row["updated_at"] or data.get("updated_at") or "")
    return data


def save_lottery_settings(
    *,
    period: str,
    title: str,
    note: str,
    prizes: str,
    status: str,
    cost_per_chance: int,
    max_chances_per_user: int,
) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    period = str(period or "").strip()
    if not _PERIOD_RE.fullmatch(period):
        raise ValueError("期別請使用 YYYY-MM，例如 2026-10。")

    title = str(title or "").strip()
    if not title:
        raise ValueError("請填寫抽獎名稱。")
    if len(title) > 100:
        raise ValueError("抽獎名稱最多 100 字。")

    status = str(status or "open").strip().lower()
    if status not in {"open", "closed"}:
        raise ValueError("抽獎狀態不正確。")

    cost = int(cost_per_chance or 0)
    maximum = int(max_chances_per_user or 0)
    if cost < 1 or cost > 100000:
        raise ValueError("每次抽獎點數需介於 1～100000。")
    if maximum < 1 or maximum > 1000:
        raise ValueError("每人最多次數需介於 1～1000。")

    data = {
        "period": period,
        "title": title,
        "note": str(note or "").strip()[:2000],
        "prizes": str(prizes or "").strip()[:4000],
        "status": status,
        "cost_per_chance": cost,
        "max_chances_per_user": maximum,
        "updated_at": get_taipei_now_iso(),
    }

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO lottery_settings (key, data, updated_at)
            VALUES ('current', ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
            """,
            (
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                data["updated_at"],
            ),
        )
        conn.commit()
    return data


def _entries(period: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT user_id, chances, points_used, updated_at
            FROM lottery_entries
            WHERE period = ? AND chances > 0
            ORDER BY chances DESC, updated_at ASC
            """,
            (str(period),),
        ).fetchall()
    return [dict(row) for row in rows]


def _draws(limit: int = 80) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT rowid AS draw_rowid, period, prize, winner_id, drawn_by, drawn_at
            FROM lottery_draws
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 80), 300)),),
        ).fetchall()
    return [dict(row) for row in rows]


def build_lottery_admin_snapshot() -> dict[str, Any]:
    ensure_lottery_admin_tables()
    settings = get_lottery_settings()
    period = str(settings.get("period") or get_taipei_now().strftime("%Y-%m"))
    entries = _entries(period)
    draws = _draws()
    total_chances = sum(int(row.get("chances") or 0) for row in entries)
    total_points = sum(int(row.get("points_used") or 0) for row in entries)
    free_draws = [row for row in draws if str(row.get("period") or "") == "free-reaction"]
    point_draws = [row for row in draws if str(row.get("period") or "") != "free-reaction"]

    return {
        "settings": settings,
        "entries": entries,
        "draws": draws,
        "free_draws": free_draws,
        "point_draws": point_draws,
        "participant_count": len(entries),
        "total_chances": total_chances,
        "total_points": total_points,
    }


__all__ = [
    "build_lottery_admin_snapshot",
    "ensure_lottery_admin_tables",
    "get_lottery_settings",
    "save_lottery_settings",
]
