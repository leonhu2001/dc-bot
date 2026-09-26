from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect(db_file: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_file) if db_file is not None else _default_db_path()
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_ticket_archive_tables(db_file: Path | str | None = None) -> None:
    conn = _connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ticket_archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_channel_id TEXT NOT NULL UNIQUE,
                ticket_channel_name TEXT,
                order_id INTEGER,
                order_no TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                closed_by_discord_id TEXT,
                closed_by_display_name TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                closed_at TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ticket_archives_customer
                ON ticket_archives(customer_discord_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_archives_customer_service
                ON ticket_archives(customer_service_discord_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_archives_closed_at
                ON ticket_archives(closed_at);

            CREATE TABLE IF NOT EXISTS ticket_archive_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                discord_message_id TEXT,
                author_discord_id TEXT,
                author_display_name TEXT,
                author_is_bot INTEGER NOT NULL DEFAULT 0,
                content TEXT,
                attachments_json TEXT,
                embeds_json TEXT,
                reply_to_message_id TEXT,
                created_at TEXT NOT NULL,
                edited_at TEXT,
                FOREIGN KEY (archive_id)
                    REFERENCES ticket_archives(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ticket_archive_messages_archive
                ON ticket_archive_messages(archive_id, id);

            CREATE INDEX IF NOT EXISTS idx_ticket_archive_messages_author
                ON ticket_archive_messages(author_discord_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_ticket_archive(
    *,
    ticket_channel_id: int | str,
    ticket_channel_name: str,
    order_id: int | None,
    order_no: str | None,
    customer_discord_id: int | str | None,
    customer_display_name: str | None,
    customer_service_discord_id: int | str | None,
    customer_service_display_name: str | None,
    closed_by_discord_id: int | str | None,
    closed_by_display_name: str | None,
    closed_at: str,
    archived_at: str,
    messages: list[dict[str, Any]],
    db_file: Path | str | None = None,
) -> int:
    ensure_ticket_archive_tables(db_file)
    conn = _connect(db_file)

    try:
        row = conn.execute(
            """
            SELECT id
            FROM ticket_archives
            WHERE ticket_channel_id = ?
            LIMIT 1
            """,
            (str(ticket_channel_id),),
        ).fetchone()

        params = (
            str(ticket_channel_name or ""),
            int(order_id) if order_id is not None else None,
            str(order_no or ""),
            str(customer_discord_id or ""),
            str(customer_display_name or ""),
            str(customer_service_discord_id or ""),
            str(customer_service_display_name or ""),
            str(closed_by_discord_id or ""),
            str(closed_by_display_name or ""),
            len(messages),
            str(closed_at),
            str(archived_at),
        )

        if row is None:
            cur = conn.execute(
                """
                INSERT INTO ticket_archives (
                    ticket_channel_id,
                    ticket_channel_name,
                    order_id,
                    order_no,
                    customer_discord_id,
                    customer_display_name,
                    customer_service_discord_id,
                    customer_service_display_name,
                    closed_by_discord_id,
                    closed_by_display_name,
                    message_count,
                    closed_at,
                    archived_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(ticket_channel_id),) + params,
            )
            archive_id = int(cur.lastrowid)
        else:
            archive_id = int(row["id"])
            conn.execute(
                """
                UPDATE ticket_archives
                SET ticket_channel_name = ?,
                    order_id = ?,
                    order_no = ?,
                    customer_discord_id = ?,
                    customer_display_name = ?,
                    customer_service_discord_id = ?,
                    customer_service_display_name = ?,
                    closed_by_discord_id = ?,
                    closed_by_display_name = ?,
                    message_count = ?,
                    closed_at = ?,
                    archived_at = ?
                WHERE id = ?
                """,
                params + (archive_id,),
            )
            conn.execute(
                "DELETE FROM ticket_archive_messages WHERE archive_id = ?",
                (archive_id,),
            )

        payload = []
        for item in messages:
            payload.append(
                (
                    archive_id,
                    str(item.get("discord_message_id") or ""),
                    str(item.get("author_discord_id") or ""),
                    str(item.get("author_display_name") or ""),
                    1 if item.get("author_is_bot") else 0,
                    str(item.get("content") or ""),
                    json.dumps(
                        item.get("attachments") or [],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        item.get("embeds") or [],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    str(item.get("reply_to_message_id") or ""),
                    str(item.get("created_at") or ""),
                    str(item.get("edited_at") or ""),
                )
            )

        if payload:
            conn.executemany(
                """
                INSERT INTO ticket_archive_messages (
                    archive_id,
                    discord_message_id,
                    author_discord_id,
                    author_display_name,
                    author_is_bot,
                    content,
                    attachments_json,
                    embeds_json,
                    reply_to_message_id,
                    created_at,
                    edited_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

        conn.commit()
        return archive_id
    finally:
        conn.close()


def list_ticket_archives(
    *,
    search: str | None = None,
    limit: int = 100,
    db_file: Path | str | None = None,
) -> list[dict[str, Any]]:
    ensure_ticket_archive_tables(db_file)
    conn = _connect(db_file)

    try:
        keyword = str(search or "").strip()
        params: list[Any] = []

        where = ""
        if keyword:
            like = f"%{keyword}%"
            where = """
                WHERE
                    a.ticket_channel_name LIKE ?
                    OR a.order_no LIKE ?
                    OR CAST(a.order_id AS TEXT) LIKE ?
                    OR a.customer_display_name LIKE ?
                    OR a.customer_discord_id LIKE ?
                    OR a.customer_service_display_name LIKE ?
                    OR a.customer_service_discord_id LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM ticket_archive_messages m
                        WHERE m.archive_id = a.id
                          AND (
                              m.content LIKE ?
                              OR m.author_display_name LIKE ?
                              OR m.author_discord_id LIKE ?
                          )
                    )
            """
            params.extend([like] * 10)

        rows = conn.execute(
            f"""
            SELECT a.*
            FROM ticket_archives a
            {where}
            ORDER BY a.closed_at DESC, a.id DESC
            LIMIT ?
            """,
            params + [max(1, min(int(limit), 500))],
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_ticket_archive(
    archive_id: int,
    *,
    db_file: Path | str | None = None,
) -> dict[str, Any] | None:
    ensure_ticket_archive_tables(db_file)
    conn = _connect(db_file)

    try:
        archive_row = conn.execute(
            "SELECT * FROM ticket_archives WHERE id = ? LIMIT 1",
            (int(archive_id),),
        ).fetchone()

        if archive_row is None:
            return None

        message_rows = conn.execute(
            """
            SELECT *
            FROM ticket_archive_messages
            WHERE archive_id = ?
            ORDER BY id ASC
            """,
            (int(archive_id),),
        ).fetchall()

        messages: list[dict[str, Any]] = []
        for row in message_rows:
            item = dict(row)
            try:
                item["attachments"] = json.loads(
                    str(item.pop("attachments_json", "") or "[]")
                )
            except Exception:
                item["attachments"] = []

            try:
                item["embeds"] = json.loads(
                    str(item.pop("embeds_json", "") or "[]")
                )
            except Exception:
                item["embeds"] = []

            messages.append(item)

        return {
            "archive": dict(archive_row),
            "messages": messages,
        }
    finally:
        conn.close()
