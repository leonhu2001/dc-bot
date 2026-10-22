from __future__ import annotations

import json
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from core.time_utils import get_taipei_now, get_taipei_now_iso
from web.app.config import config


ROOT = Path(__file__).resolve().parents[3]
BOT_DB = ROOT / "bot.db"
_PERIOD_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
DISCORD_API_BASE = "https://discord.com/api/v10"
GIVEAWAY_EMOJI = "🎉"
FREE_GIVEAWAY_PERIOD = "free-reaction"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(BOT_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _discord_headers() -> dict[str, str]:
    token = str(config.DISCORD_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("網站尚未設定 Discord Bot Token，無法操作抽獎頻道。")
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def _lottery_channel_id() -> str:
    channel_id = str(config.LOTTERY_ANNOUNCE_CHANNEL_ID or "").strip()
    if not channel_id:
        raise RuntimeError("抽獎公告頻道尚未設定。")
    return channel_id


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

            CREATE TABLE IF NOT EXISTS lottery_free_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL UNIQUE,
                prize TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                drawn_by INTEGER,
                drawn_at TEXT,
                winner_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_lottery_free_events_status
            ON lottery_free_events(status, id DESC);
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


def _active_free_event() -> dict[str, Any] | None:
    ensure_lottery_admin_tables()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM lottery_free_events
            WHERE status = 'open'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row is not None else None


def _free_event_message_url(event: dict[str, Any]) -> str:
    guild_id = str(config.DISCORD_GUILD_ID or "").strip()
    channel_id = str(event.get("channel_id") or "").strip()
    message_id = str(event.get("message_id") or "").strip()
    if not guild_id or not channel_id or not message_id:
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _collect_free_participants(event: dict[str, Any]) -> list[dict[str, Any]]:
    channel_id = str(event.get("channel_id") or "").strip()
    message_id = str(event.get("message_id") or "").strip()
    if not channel_id or not message_id:
        raise RuntimeError("目前抽獎活動缺少 Discord 訊息資料。")

    emoji = quote(GIVEAWAY_EMOJI, safe="")
    url = (
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        f"/reactions/{emoji}"
    )
    participants: dict[int, dict[str, Any]] = {}
    after = ""

    for _ in range(50):
        params: dict[str, Any] = {"limit": 100}
        if after:
            params["after"] = after
        response = requests.get(
            url,
            headers=_discord_headers(),
            params=params,
            timeout=15,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"讀取 Discord 抽獎名單失敗（HTTP {response.status_code}）。"
            )

        batch = response.json()
        if not isinstance(batch, list):
            raise RuntimeError("Discord 抽獎名單格式不正確。")

        for user in batch:
            if not isinstance(user, dict) or bool(user.get("bot")):
                continue
            try:
                user_id = int(str(user.get("id") or "0"))
            except ValueError:
                continue
            if user_id > 0:
                participants[user_id] = user

        if len(batch) < 100:
            break
        after = str((batch[-1] or {}).get("id") or "").strip()
        if not after:
            break

    return list(participants.values())


def publish_free_giveaway(
    *,
    prize: str,
    description: str,
    actor_discord_id: str | int,
) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    if _active_free_event() is not None:
        raise ValueError("目前已有一場免費抽獎正在報名，請先開獎後再建立下一場。")

    prize_text = str(prize or "").strip()
    if not prize_text:
        raise ValueError("請填寫抽獎獎品。")
    if len(prize_text) > 300:
        raise ValueError("抽獎獎品最多 300 字。")
    description_text = str(description or "").strip()[:1000]

    try:
        actor_id = int(str(actor_discord_id or "0"))
    except ValueError as exc:
        raise ValueError("目前登入帳號缺少 Discord ID。") from exc
    if actor_id <= 0:
        raise ValueError("目前登入帳號缺少 Discord ID。")

    channel_id = _lottery_channel_id()
    embed: dict[str, Any] = {
        "title": "🎁 魔丸全店抽獎活動",
        "description": (
            f"**獎品：** {prize_text}\n\n"
            f"**參加方式：** 按下方 {GIVEAWAY_EMOJI} 表情即可參加\n"
            "**參加限制：** 每人限參加 1 次\n"
            "**消耗：** 不消耗點數、不消耗任何東西"
        ),
        "color": 0xE0BA64,
        "footer": {"text": "開獎時會從按下 🎉 的成員中隨機抽出得獎者。"},
    }
    if description_text:
        embed["fields"] = [
            {
                "name": "活動說明",
                "value": description_text,
                "inline": False,
            }
        ]

    response = requests.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        headers=_discord_headers(),
        json={
            "content": "@everyone 🎁 魔丸全店抽獎開始！按下 🎉 參加抽獎！",
            "embeds": [embed],
            "allowed_mentions": {"parse": ["everyone"]},
        },
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(
            f"發送抽獎報名訊息失敗（HTTP {response.status_code}）。"
        )

    payload = response.json()
    message_id = str(payload.get("id") or "").strip()
    if not message_id:
        raise RuntimeError("Discord 沒有回傳抽獎訊息 ID。")

    emoji = quote(GIVEAWAY_EMOJI, safe="")
    reaction_response = requests.put(
        (
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
            f"/reactions/{emoji}/@me"
        ),
        headers=_discord_headers(),
        timeout=15,
    )
    if reaction_response.status_code not in {200, 204}:
        try:
            requests.delete(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
                headers=_discord_headers(),
                timeout=10,
            )
        except requests.RequestException:
            pass
        raise RuntimeError(
            f"抽獎訊息已建立，但加入 🎉 反應失敗（HTTP {reaction_response.status_code}）。"
        )

    created_at = get_taipei_now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO lottery_free_events (
                channel_id, message_id, prize, description, status,
                created_by, created_at, winner_count
            )
            VALUES (?, ?, ?, ?, 'open', ?, ?, 0)
            """,
            (
                channel_id,
                message_id,
                prize_text,
                description_text,
                actor_id,
                created_at,
            ),
        )
        conn.commit()
        event_id = int(cursor.lastrowid)

    return {
        "id": event_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "prize": prize_text,
        "description": description_text,
        "status": "open",
        "created_by": actor_id,
        "created_at": created_at,
    }


def draw_free_giveaway(
    *,
    winners: int,
    actor_discord_id: str | int,
) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    event = _active_free_event()
    if event is None:
        raise ValueError("目前沒有等待開獎的免費抽獎。")

    try:
        actor_id = int(str(actor_discord_id or "0"))
    except ValueError as exc:
        raise ValueError("目前登入帳號缺少 Discord ID。") from exc
    if actor_id <= 0:
        raise ValueError("目前登入帳號缺少 Discord ID。")

    winner_count = int(winners or 0)
    if winner_count < 1 or winner_count > 50:
        raise ValueError("得獎人數需介於 1～50 人。")

    participants = _collect_free_participants(event)
    if not participants:
        raise ValueError("目前還沒有人按 🎉 參加抽獎。")

    picked_count = min(winner_count, len(participants))
    picked = secrets.SystemRandom().sample(participants, picked_count)
    prize_text = str(event.get("prize") or "抽獎獎品")
    winner_mentions = "\n".join(
        f"{index}. <@{str(user.get('id') or '')}>"
        for index, user in enumerate(picked, start=1)
    )

    channel_id = str(event.get("channel_id") or "").strip()
    message_id = str(event.get("message_id") or "").strip()
    result_response = requests.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        headers=_discord_headers(),
        json={
            "content": "@everyone 🎉 魔丸全店抽獎開獎啦！恭喜得獎者！",
            "embeds": [
                {
                    "title": "🎉 魔丸全店抽獎開獎",
                    "description": (
                        f"**獎品：** {prize_text}\n"
                        f"**參加人數：** {len(participants)} 人\n"
                        f"**得獎人數：** {picked_count} 人\n\n"
                        f"{winner_mentions}"
                    ),
                    "color": 0x45B96B,
                    "fields": [
                        {
                            "name": "原抽獎訊息",
                            "value": f"https://discord.com/channels/{str(config.DISCORD_GUILD_ID or '@me')}/{channel_id}/{message_id}",
                            "inline": False,
                        }
                    ],
                    "footer": {
                        "text": "本次抽獎不消耗點數，每人依 🎉 反應限算一次。"
                    },
                }
            ],
            "allowed_mentions": {"parse": ["everyone", "users"]},
        },
        timeout=15,
    )
    if result_response.status_code not in {200, 201}:
        raise RuntimeError(
            f"抽獎完成，但公布結果失敗（HTTP {result_response.status_code}）。請勿重複按開獎，先確認 Discord 狀態。"
        )

    drawn_at = get_taipei_now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT status FROM lottery_free_events WHERE id = ? LIMIT 1",
            (int(event["id"]),),
        ).fetchone()
        if current is None or str(current["status"] or "") != "open":
            conn.rollback()
            raise ValueError("這場抽獎已經開過獎，請重新整理頁面。")

        for user in picked:
            conn.execute(
                """
                INSERT INTO lottery_draws (
                    period, prize, winner_id, drawn_by, drawn_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    FREE_GIVEAWAY_PERIOD,
                    prize_text,
                    int(str(user.get("id") or "0")),
                    actor_id,
                    drawn_at,
                ),
            )

        conn.execute(
            """
            UPDATE lottery_free_events
            SET status = 'drawn',
                drawn_by = ?,
                drawn_at = ?,
                winner_count = ?
            WHERE id = ?
            """,
            (actor_id, drawn_at, picked_count, int(event["id"])),
        )
        conn.commit()

    return {
        "event_id": int(event["id"]),
        "participant_count": len(participants),
        "winner_count": picked_count,
        "winner_ids": [int(str(user.get("id") or "0")) for user in picked],
    }


def build_lottery_admin_snapshot() -> dict[str, Any]:
    ensure_lottery_admin_tables()
    settings = get_lottery_settings()
    period = str(settings.get("period") or get_taipei_now().strftime("%Y-%m"))
    entries = _entries(period)
    draws = _draws()
    total_chances = sum(int(row.get("chances") or 0) for row in entries)
    total_points = sum(int(row.get("points_used") or 0) for row in entries)
    free_draws = [row for row in draws if str(row.get("period") or "") == FREE_GIVEAWAY_PERIOD]
    point_draws = [row for row in draws if str(row.get("period") or "") != FREE_GIVEAWAY_PERIOD]
    free_event = _active_free_event()
    free_participant_count: int | None = None
    free_participant_error = ""

    if free_event is not None:
        free_event["message_url"] = _free_event_message_url(free_event)
        try:
            free_participant_count = len(_collect_free_participants(free_event))
        except Exception as exc:
            free_participant_error = f"{type(exc).__name__}: {exc}"

    return {
        "settings": settings,
        "entries": entries,
        "draws": draws,
        "free_draws": free_draws,
        "point_draws": point_draws,
        "participant_count": len(entries),
        "total_chances": total_chances,
        "total_points": total_points,
        "free_event": free_event,
        "free_participant_count": free_participant_count,
        "free_participant_error": free_participant_error,
    }


__all__ = [
    "build_lottery_admin_snapshot",
    "draw_free_giveaway",
    "ensure_lottery_admin_tables",
    "get_lottery_settings",
    "publish_free_giveaway",
    "save_lottery_settings",
]
