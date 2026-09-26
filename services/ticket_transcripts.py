from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TAIPEI_TZ = timezone(timedelta(hours=8))
MAX_TRANSCRIPT_MESSAGES = 5000


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _db_path() -> Path:
    return _root_dir() / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def ensure_ticket_transcript_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ticket_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                channel_name TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                closed_by_discord_id TEXT,
                closed_by_display_name TEXT,
                closed_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                participant_count INTEGER NOT NULL DEFAULT 0,
                participants_json TEXT NOT NULL DEFAULT '[]',
                transcript_text TEXT NOT NULL DEFAULT '',
                transcript_html TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_ticket_transcripts_channel
                ON ticket_transcripts(ticket_channel_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_transcripts_order
                ON ticket_transcripts(order_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_transcripts_customer
                ON ticket_transcripts(customer_discord_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_transcripts_closed_at
                ON ticket_transcripts(closed_at);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _message_datetime(message) -> str:
    dt = getattr(message, "created_at", None)
    if dt is None:
        return ""

    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


def _author_payload(message) -> dict:
    author = getattr(message, "author", None)
    author_id = _safe_text(getattr(author, "id", ""))
    display_name = _safe_text(
        getattr(author, "display_name", None)
        or getattr(author, "global_name", None)
        or getattr(author, "name", None)
        or author_id
        or "未知使用者"
    )

    avatar_url = ""
    try:
        avatar_url = _safe_text(getattr(getattr(author, "display_avatar", None), "url", ""))
    except Exception:
        avatar_url = ""

    return {
        "id": author_id,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "is_bot": bool(getattr(author, "bot", False)),
    }


def _attachment_payload(message) -> list[dict]:
    result: list[dict] = []

    for attachment in list(getattr(message, "attachments", []) or []):
        result.append(
            {
                "filename": _safe_text(getattr(attachment, "filename", "附件")) or "附件",
                "url": _safe_text(getattr(attachment, "url", "")),
                "content_type": _safe_text(getattr(attachment, "content_type", "")),
                "size": int(getattr(attachment, "size", 0) or 0),
            }
        )

    return result


def _embed_payload(message) -> list[dict]:
    result: list[dict] = []

    for embed in list(getattr(message, "embeds", []) or []):
        fields = []
        for field in list(getattr(embed, "fields", []) or []):
            fields.append(
                {
                    "name": _safe_text(getattr(field, "name", "")),
                    "value": _safe_text(getattr(field, "value", "")),
                }
            )

        result.append(
            {
                "title": _safe_text(getattr(embed, "title", "")),
                "description": _safe_text(getattr(embed, "description", "")),
                "fields": fields,
            }
        )

    return result


def _clean_message_content(message) -> str:
    try:
        clean = getattr(message, "clean_content", None)
        if clean is not None:
            return str(clean)
    except Exception:
        pass

    return str(getattr(message, "content", "") or "")


def _escape_multiline(value: str) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def _render_message_html(item: dict) -> str:
    author = item["author"]
    display_name = html.escape(author["display_name"])
    timestamp = html.escape(item["created_at"])
    avatar_url = html.escape(author["avatar_url"], quote=True)
    author_id = html.escape(author["id"])
    bot_badge = '<span class="tx-bot">BOT</span>' if author["is_bot"] else ""

    if avatar_url:
        avatar = (
            f'<img class="tx-avatar" src="{avatar_url}" '
            f'alt="{display_name}" loading="lazy">'
        )
    else:
        initial = html.escape((author["display_name"] or "?")[:1])
        avatar = f'<span class="tx-avatar tx-avatar-fallback">{initial}</span>'

    body_parts: list[str] = []
    if item["content"]:
        body_parts.append(f'<div class="tx-content">{_escape_multiline(item["content"])}</div>')

    for embed_item in item["embeds"]:
        embed_bits: list[str] = []
        if embed_item["title"]:
            embed_bits.append(
                f'<div class="tx-embed-title">{_escape_multiline(embed_item["title"])}</div>'
            )
        if embed_item["description"]:
            embed_bits.append(
                f'<div class="tx-embed-description">{_escape_multiline(embed_item["description"])}</div>'
            )
        for field in embed_item["fields"]:
            embed_bits.append(
                '<div class="tx-embed-field">'
                f'<strong>{_escape_multiline(field["name"])}</strong>'
                f'<span>{_escape_multiline(field["value"])}</span>'
                '</div>'
            )
        if embed_bits:
            body_parts.append('<div class="tx-embed">' + "".join(embed_bits) + '</div>')

    for attachment in item["attachments"]:
        filename = html.escape(attachment["filename"])
        url = html.escape(attachment["url"], quote=True)
        content_type = attachment["content_type"].lower()
        if url and content_type.startswith("image/"):
            body_parts.append(
                '<div class="tx-attachment tx-image">'
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
                f'<img src="{url}" alt="{filename}" loading="lazy">'
                '</a>'
                f'<span>{filename}</span>'
                '</div>'
            )
        elif url:
            body_parts.append(
                '<div class="tx-attachment">'
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{filename}</a>'
                '</div>'
            )
        else:
            body_parts.append(f'<div class="tx-attachment">{filename}</div>')

    if not body_parts:
        body_parts.append('<div class="tx-content tx-muted">（無文字內容）</div>')

    return (
        '<article class="tx-message">'
        f'{avatar}'
        '<div class="tx-message-main">'
        '<div class="tx-meta">'
        f'<strong>{display_name}</strong>{bot_badge}'
        f'<span class="tx-author-id">{author_id}</span>'
        f'<time>{timestamp}</time>'
        '</div>'
        + "".join(body_parts)
        + '</div>'
        '</article>'
    )


def _render_transcript_html(
    *,
    channel_name: str,
    messages: list[dict],
    truncated: bool,
) -> str:
    warning = ""
    if truncated:
        warning = (
            '<div class="tx-warning">'
            f'紀錄超過 {MAX_TRANSCRIPT_MESSAGES:,} 則，本頁僅保留關閉前可讀取的前 '
            f'{MAX_TRANSCRIPT_MESSAGES:,} 則訊息。'
            '</div>'
        )

    empty = (
        '<div class="tx-empty">此票口沒有可保存的訊息。</div>'
        if not messages
        else ""
    )

    return (
        '<section class="ticket-transcript">'
        '<div class="tx-head">'
        f'<strong>#{html.escape(channel_name or "ticket")}</strong>'
        f'<span>{len(messages):,} 則訊息</span>'
        '</div>'
        f'{warning}{empty}'
        '<div class="tx-messages">'
        + "".join(_render_message_html(item) for item in messages)
        + '</div>'
        '</section>'
    )


def _render_transcript_text(messages: list[dict], *, truncated: bool) -> str:
    lines: list[str] = []
    if truncated:
        lines.append(
            f"[系統] 訊息超過 {MAX_TRANSCRIPT_MESSAGES:,} 則，本紀錄已截斷。"
        )

    for item in messages:
        author = item["author"]["display_name"]
        timestamp = item["created_at"]
        content = item["content"].strip()
        lines.append(f"[{timestamp}] {author}: {content}")

        for attachment in item["attachments"]:
            lines.append(
                f"  [附件] {attachment['filename']} {attachment['url']}".rstrip()
            )

        for embed_item in item["embeds"]:
            if embed_item["title"]:
                lines.append(f"  [Embed] {embed_item['title']}")
            if embed_item["description"]:
                lines.append(f"  {embed_item['description']}")

    return "\n".join(lines)


def _find_order_for_ticket(ticket_channel_id: str) -> sqlite3.Row | None:
    conn = _connect()
    try:
        return conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE ticket_channel_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (ticket_channel_id,),
        ).fetchone()
    finally:
        conn.close()


async def archive_ticket_channel(
    channel,
    *,
    closed_by,
    customer_id: int | str | None = None,
) -> dict:
    """Capture a Discord ticket before deletion and persist a sanitized web transcript."""

    ensure_ticket_transcript_tables()

    ticket_channel_id = _safe_text(getattr(channel, "id", ""))
    if not ticket_channel_id:
        raise ValueError("找不到票口頻道 ID，無法建立聊天紀錄。")

    messages: list[dict] = []
    participants: dict[str, dict] = {}

    try:
        async for message in channel.history(
            limit=MAX_TRANSCRIPT_MESSAGES,
            oldest_first=True,
        ):
            author = _author_payload(message)
            if author["id"]:
                participants[author["id"]] = author

            messages.append(
                {
                    "id": _safe_text(getattr(message, "id", "")),
                    "created_at": _message_datetime(message),
                    "author": author,
                    "content": _clean_message_content(message),
                    "attachments": _attachment_payload(message),
                    "embeds": _embed_payload(message),
                }
            )
    except Exception as exc:
        raise RuntimeError(f"讀取票口聊天紀錄失敗：{exc}") from exc

    truncated = len(messages) >= MAX_TRANSCRIPT_MESSAGES
    order = _find_order_for_ticket(ticket_channel_id)

    resolved_customer_id = _safe_text(
        customer_id
        or (order["customer_discord_id"] if order is not None else "")
    )
    customer_display_name = _safe_text(
        order["customer_display_name"] if order is not None else ""
    )

    channel_name = _safe_text(getattr(channel, "name", "ticket")) or "ticket"
    closed_by_id = _safe_text(getattr(closed_by, "id", ""))
    closed_by_name = _safe_text(
        getattr(closed_by, "display_name", None)
        or getattr(closed_by, "name", None)
        or closed_by_id
    )

    now = _now_iso()
    transcript_html = _render_transcript_html(
        channel_name=channel_name,
        messages=messages,
        truncated=truncated,
    )
    transcript_text = _render_transcript_text(
        messages,
        truncated=truncated,
    )

    participant_payload = [
        {
            "id": item["id"],
            "display_name": item["display_name"],
            "avatar_url": item["avatar_url"],
            "is_bot": item["is_bot"],
        }
        for item in participants.values()
    ]

    conn = _connect()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM ticket_transcripts
            WHERE ticket_channel_id = ?
            LIMIT 1
            """,
            (ticket_channel_id,),
        ).fetchone()

        values = {
            "order_id": int(order["id"]) if order is not None else None,
            "ticket_channel_id": ticket_channel_id,
            "dispatch_message_id": _safe_text(
                order["dispatch_message_id"] if order is not None else ""
            ),
            "receipt_id": _safe_text(
                order["bot_order_no"] if order is not None else ""
            ),
            "channel_name": channel_name,
            "customer_discord_id": resolved_customer_id,
            "customer_display_name": customer_display_name,
            "closed_by_discord_id": closed_by_id,
            "closed_by_display_name": closed_by_name,
            "closed_at": now,
            "message_count": len(messages),
            "participant_count": len(participant_payload),
            "participants_json": json.dumps(
                participant_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "transcript_text": transcript_text,
            "transcript_html": transcript_html,
            "updated_at": now,
        }

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO ticket_transcripts (
                    order_id,
                    ticket_channel_id,
                    dispatch_message_id,
                    receipt_id,
                    channel_name,
                    customer_discord_id,
                    customer_display_name,
                    closed_by_discord_id,
                    closed_by_display_name,
                    closed_at,
                    message_count,
                    participant_count,
                    participants_json,
                    transcript_text,
                    transcript_html,
                    created_at,
                    updated_at
                )
                VALUES (
                    :order_id,
                    :ticket_channel_id,
                    :dispatch_message_id,
                    :receipt_id,
                    :channel_name,
                    :customer_discord_id,
                    :customer_display_name,
                    :closed_by_discord_id,
                    :closed_by_display_name,
                    :closed_at,
                    :message_count,
                    :participant_count,
                    :participants_json,
                    :transcript_text,
                    :transcript_html,
                    :closed_at,
                    :updated_at
                )
                """,
                values,
            )
            transcript_id = int(cur.lastrowid)
        else:
            transcript_id = int(existing["id"])
            values["id"] = transcript_id
            conn.execute(
                """
                UPDATE ticket_transcripts
                SET order_id = :order_id,
                    dispatch_message_id = :dispatch_message_id,
                    receipt_id = :receipt_id,
                    channel_name = :channel_name,
                    customer_discord_id = :customer_discord_id,
                    customer_display_name = :customer_display_name,
                    closed_by_discord_id = :closed_by_discord_id,
                    closed_by_display_name = :closed_by_display_name,
                    closed_at = :closed_at,
                    message_count = :message_count,
                    participant_count = :participant_count,
                    participants_json = :participants_json,
                    transcript_text = :transcript_text,
                    transcript_html = :transcript_html,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                values,
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "id": transcript_id,
        "ticket_channel_id": ticket_channel_id,
        "order_id": values["order_id"],
        "message_count": len(messages),
        "participant_count": len(participant_payload),
        "closed_at": now,
    }
