from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from core.time_utils import get_taipei_now_iso
from services.promotion_benefits import issue_benefit, list_templates
from web.app.config import config


ROOT = Path(__file__).resolve().parents[3]
BOT_DB = ROOT / "bot.db"
DISCORD_API_BASE = "https://discord.com/api/v10"
GIVEAWAY_EMOJI = "🎉"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(BOT_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _discord_headers() -> dict[str, str]:
    token = str(config.DISCORD_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("網站尚未設定 Discord Bot Token，無法操作抽獎頻道。")
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}


def _lottery_channel_id() -> str:
    channel_id = str(config.LOTTERY_ANNOUNCE_CHANNEL_ID or "").strip()
    if not channel_id:
        raise RuntimeError("抽獎公告頻道尚未設定。")
    return channel_id


def _actor_id(value: str | int) -> int:
    try:
        actor = int(str(value or "0"))
    except ValueError as exc:
        raise ValueError("目前登入帳號缺少 Discord ID。") from exc
    if actor <= 0:
        raise ValueError("目前登入帳號缺少 Discord ID。")
    return actor


def ensure_lottery_admin_tables() -> None:
    BOT_DB.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lottery_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                channel_id TEXT,
                message_id TEXT UNIQUE,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT,
                drawn_at TEXT
            );

            CREATE TABLE IF NOT EXISTS lottery_campaign_prizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                template_id INTEGER NOT NULL,
                prize_name TEXT NOT NULL,
                winner_count INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                drawn_at TEXT,
                FOREIGN KEY(campaign_id) REFERENCES lottery_campaigns(id)
            );

            CREATE INDEX IF NOT EXISTS idx_lottery_campaign_status
            ON lottery_campaigns(status, id DESC);

            CREATE INDEX IF NOT EXISTS idx_lottery_campaign_prizes_campaign
            ON lottery_campaign_prizes(campaign_id, sort_order, id);

            CREATE TABLE IF NOT EXISTS lottery_campaign_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                prize_id INTEGER NOT NULL,
                winner_id INTEGER NOT NULL,
                issued_benefit_id INTEGER,
                drawn_by INTEGER NOT NULL,
                drawn_at TEXT NOT NULL,
                UNIQUE(campaign_id, winner_id)
            );

            CREATE INDEX IF NOT EXISTS idx_lottery_campaign_winners_campaign
            ON lottery_campaign_winners(campaign_id, prize_id, id);
            """
        )
        conn.commit()


def _campaign_row(status: str) -> dict[str, Any] | None:
    ensure_lottery_admin_tables()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lottery_campaigns WHERE status=? ORDER BY id DESC LIMIT 1",
            (status,),
        ).fetchone()
    return dict(row) if row is not None else None


def _campaign_prizes(campaign_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM lottery_campaign_prizes
            WHERE campaign_id=? ORDER BY sort_order ASC, id ASC
            """,
            (int(campaign_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _campaign_winners(campaign_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT w.*, p.prize_name
            FROM lottery_campaign_winners w
            JOIN lottery_campaign_prizes p ON p.id=w.prize_id
            WHERE w.campaign_id=? ORDER BY w.id ASC
            """,
            (int(campaign_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _message_url(campaign: dict[str, Any]) -> str:
    guild_id = str(config.DISCORD_GUILD_ID or "").strip()
    channel_id = str(campaign.get("channel_id") or "").strip()
    message_id = str(campaign.get("message_id") or "").strip()
    if not guild_id or not channel_id or not message_id:
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _collect_participants(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    channel_id = str(campaign.get("channel_id") or "").strip()
    message_id = str(campaign.get("message_id") or "").strip()
    if not channel_id or not message_id:
        raise RuntimeError("目前抽獎活動缺少 Discord 訊息資料。")

    emoji = quote(GIVEAWAY_EMOJI, safe="")
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}"
    participants: dict[int, dict[str, Any]] = {}
    after = ""
    for _ in range(50):
        params: dict[str, Any] = {"limit": 100}
        if after:
            params["after"] = after
        response = requests.get(url, headers=_discord_headers(), params=params, timeout=15)
        if response.status_code != 200:
            raise RuntimeError(f"讀取 Discord 抽獎名單失敗（HTTP {response.status_code}）。")
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


def save_campaign_draft(
    *,
    title: str,
    description: str,
    template_ids: list[int],
    winner_counts: list[int],
    actor_discord_id: str | int,
) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    if _campaign_row("open") is not None:
        raise ValueError("目前已有抽獎正在報名，請先完成開獎再建立下一場。")

    actor = _actor_id(actor_discord_id)
    title_text = str(title or "").strip()
    if not title_text:
        raise ValueError("請輸入抽獎活動名稱。")
    if len(title_text) > 120:
        raise ValueError("活動名稱最多 120 字。")
    description_text = str(description or "").strip()[:1500]

    if len(template_ids) != len(winner_counts) or not template_ids:
        raise ValueError("至少要設定一個獎項。")

    active_templates = {int(row["id"]): row for row in list_templates(include_inactive=False)}
    prizes: list[tuple[int, str, int]] = []
    for raw_template_id, raw_count in zip(template_ids, winner_counts):
        template_id = int(raw_template_id)
        count = int(raw_count)
        template = active_templates.get(template_id)
        if template is None:
            raise ValueError("有獎項已停用或不存在，請重新選擇。")
        if count < 1 or count > 50:
            raise ValueError("每個獎項的名額需介於 1～50 人。")
        prizes.append((template_id, str(template.get("name") or "福利券"), count))

    now = get_taipei_now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        draft = conn.execute(
            "SELECT id FROM lottery_campaigns WHERE status='draft' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if draft is None:
            cur = conn.execute(
                """
                INSERT INTO lottery_campaigns (
                    title, description, status, created_by, created_at, updated_at
                ) VALUES (?, ?, 'draft', ?, ?, ?)
                """,
                (title_text, description_text, actor, now, now),
            )
            campaign_id = int(cur.lastrowid)
        else:
            campaign_id = int(draft["id"])
            conn.execute(
                "UPDATE lottery_campaigns SET title=?, description=?, updated_at=? WHERE id=?",
                (title_text, description_text, now, campaign_id),
            )
            conn.execute("DELETE FROM lottery_campaign_prizes WHERE campaign_id=?", (campaign_id,))

        for index, (template_id, prize_name, count) in enumerate(prizes):
            conn.execute(
                """
                INSERT INTO lottery_campaign_prizes (
                    campaign_id, template_id, prize_name, winner_count, sort_order
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, template_id, prize_name, count, index),
            )
        conn.commit()

    return get_campaign(campaign_id)


def get_campaign(campaign_id: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM lottery_campaigns WHERE id=?", (int(campaign_id),)).fetchone()
    if row is None:
        raise LookupError("找不到抽獎活動。")
    campaign = dict(row)
    campaign["prizes"] = _campaign_prizes(int(campaign["id"]))
    campaign["winners"] = _campaign_winners(int(campaign["id"]))
    campaign["message_url"] = _message_url(campaign)
    return campaign


def publish_campaign(*, actor_discord_id: str | int) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    if _campaign_row("open") is not None:
        raise ValueError("目前已有抽獎正在報名。")
    draft = _campaign_row("draft")
    if draft is None:
        raise ValueError("請先儲存抽獎設定，再發布抽獎。")
    campaign = get_campaign(int(draft["id"]))
    if not campaign["prizes"]:
        raise ValueError("請先新增至少一個獎項。")
    _actor_id(actor_discord_id)

    prize_lines = "\n".join(
        f"{index}. **{prize['prize_name']}** × {int(prize['winner_count'])} 名"
        for index, prize in enumerate(campaign["prizes"], start=1)
    )
    description = (
        f"{str(campaign.get('description') or '').strip()}\n\n" if campaign.get("description") else ""
    ) + (
        f"**獎項**\n{prize_lines}\n\n"
        f"**參加方式：** 按下方 {GIVEAWAY_EMOJI} 表情即可參加\n"
        "**規則：** 每人僅計 1 次；同一場活動不會重複中獎"
    )
    channel_id = _lottery_channel_id()
    response = requests.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        headers=_discord_headers(),
        json={
            "content": "@everyone 🎁 魔丸抽獎開始！按下 🎉 參加抽獎！",
            "embeds": [{"title": f"🎁 {campaign['title']}", "description": description[:4000], "color": 0xE0BA64}],
            "allowed_mentions": {"parse": ["everyone"]},
        },
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"發送抽獎訊息失敗（HTTP {response.status_code}）。")
    message_id = str(response.json().get("id") or "").strip()
    if not message_id:
        raise RuntimeError("Discord 沒有回傳抽獎訊息 ID。")

    emoji = quote(GIVEAWAY_EMOJI, safe="")
    reaction = requests.put(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
        headers=_discord_headers(),
        timeout=15,
    )
    if reaction.status_code not in {200, 204}:
        raise RuntimeError(f"抽獎訊息已建立，但加入 🎉 失敗（HTTP {reaction.status_code}）。")

    now = get_taipei_now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE lottery_campaigns
            SET status='open', channel_id=?, message_id=?, published_at=?, updated_at=?
            WHERE id=? AND status='draft'
            """,
            (channel_id, message_id, now, now, int(campaign["id"])),
        )
        conn.commit()
    return get_campaign(int(campaign["id"]))


def draw_campaign(
    *,
    actor_discord_id: str | int,
    prize_id: int | None = None,
) -> dict[str, Any]:
    ensure_lottery_admin_tables()
    actor = _actor_id(actor_discord_id)
    open_row = _campaign_row("open")
    if open_row is None:
        raise ValueError("目前沒有等待開獎的活動。")
    campaign = get_campaign(int(open_row["id"]))
    participants = _collect_participants(campaign)
    if not participants:
        raise ValueError("目前還沒有人按 🎉 參加抽獎。")

    drawn_user_ids = {int(row["winner_id"]) for row in campaign["winners"]}
    available = [u for u in participants if int(str(u.get("id") or "0")) not in drawn_user_ids]
    pending = [p for p in campaign["prizes"] if not p.get("drawn_at")]
    if prize_id:
        pending = [p for p in pending if int(p["id"]) == int(prize_id)]
        if not pending:
            raise ValueError("這個獎項已經開過獎或不存在。")
    if not pending:
        raise ValueError("這場活動已沒有待開獎項。")

    results: list[dict[str, Any]] = []
    rng = secrets.SystemRandom()
    now = get_taipei_now_iso()

    for prize in pending:
        wanted = int(prize["winner_count"])
        picked = rng.sample(available, min(wanted, len(available))) if available else []
        prize_winners: list[int] = []
        for user in picked:
            user_id = int(str(user.get("id") or "0"))
            issued_id = issue_benefit(
                template_id=int(prize["template_id"]),
                customer_discord_id=user_id,
                actor_discord_id=actor,
                note=f"抽獎活動：{campaign['title']}",
            )
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO lottery_campaign_winners (
                        campaign_id, prize_id, winner_id, issued_benefit_id, drawn_by, drawn_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (int(campaign["id"]), int(prize["id"]), user_id, int(issued_id), actor, now),
                )
                conn.commit()
            prize_winners.append(user_id)
            available = [candidate for candidate in available if int(str(candidate.get("id") or "0")) != user_id]

        with _connect() as conn:
            conn.execute("UPDATE lottery_campaign_prizes SET drawn_at=? WHERE id=?", (now, int(prize["id"])))
            conn.commit()
        results.append({"prize": prize, "winner_ids": prize_winners, "shortage": max(0, wanted - len(prize_winners))})

    lines: list[str] = []
    for result in results:
        prize = result["prize"]
        winners = result["winner_ids"]
        mentions = "、".join(f"<@{user_id}>" for user_id in winners) if winners else "無可用參加者"
        shortage = f"（尚缺 {result['shortage']} 名）" if result["shortage"] else ""
        lines.append(f"**{prize['prize_name']}**：{mentions}{shortage}")

    channel_id = str(campaign.get("channel_id") or "")
    response = requests.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        headers=_discord_headers(),
        json={
            "content": "@everyone 🎉 抽獎開獎！恭喜得獎者！",
            "embeds": [{
                "title": f"🎉 {campaign['title']}｜開獎結果",
                "description": "\n\n".join(lines)[:4000],
                "color": 0x45B96B,
            }],
            "allowed_mentions": {"parse": ["everyone", "users"]},
        },
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"得獎券已發放，但 Discord 公布結果失敗（HTTP {response.status_code}）。")

    remaining = _campaign_prizes(int(campaign["id"]))
    if all(bool(row.get("drawn_at")) for row in remaining):
        with _connect() as conn:
            conn.execute(
                "UPDATE lottery_campaigns SET status='drawn', drawn_at=?, updated_at=? WHERE id=?",
                (now, now, int(campaign["id"])),
            )
            conn.commit()

    return {
        "campaign_id": int(campaign["id"]),
        "participant_count": len(participants),
        "results": results,
    }


def build_lottery_admin_snapshot() -> dict[str, Any]:
    ensure_lottery_admin_tables()
    templates = list_templates(include_inactive=False)
    open_campaign = _campaign_row("open")
    draft_campaign = _campaign_row("draft") if open_campaign is None else None
    current = get_campaign(int(open_campaign["id"])) if open_campaign else (get_campaign(int(draft_campaign["id"])) if draft_campaign else None)

    participant_count: int | None = None
    participant_error = ""
    if open_campaign:
        try:
            participant_count = len(_collect_participants(current or open_campaign))
        except Exception as exc:
            participant_error = f"{type(exc).__name__}: {exc}"

    with _connect() as conn:
        history_rows = conn.execute(
            "SELECT * FROM lottery_campaigns WHERE status='drawn' ORDER BY id DESC LIMIT 20"
        ).fetchall()
    history = []
    for row in history_rows:
        item = get_campaign(int(row["id"]))
        history.append(item)

    return {
        "templates": templates,
        "campaign": current,
        "is_open": bool(open_campaign),
        "is_draft": bool(draft_campaign),
        "participant_count": participant_count,
        "participant_error": participant_error,
        "history": history,
        "channel_id": _lottery_channel_id(),
    }


__all__ = [
    "build_lottery_admin_snapshot",
    "draw_campaign",
    "ensure_lottery_admin_tables",
    "publish_campaign",
    "save_campaign_draft",
]
