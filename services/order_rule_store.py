from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _path(db_file: str | Path | None = None) -> Path:
    return Path(db_file) if db_file is not None else default_db_path()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_order_rule_store(db_file: str | Path | None = None) -> None:
    path = _path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_rule_overrides (
                rule_key TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_by_discord_id TEXT,
                updated_by_display_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_rule_override_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT,
                source_version INTEGER,
                actor_discord_id TEXT,
                actor_display_name TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(rule_key, version)
            );

            CREATE INDEX IF NOT EXISTS idx_order_rule_override_versions_rule
            ON order_rule_override_versions(rule_key, version DESC);
            """
        )
        conn.commit()


def _decode_payload(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_active_overrides(
    db_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = _path(db_file)
    if not path.exists():
        return {}

    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=2.0,
        )
    except sqlite3.Error:
        return {}

    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='order_rule_overrides'
            LIMIT 1
            """
        ).fetchone()
        if table is None:
            return {}

        rows = conn.execute(
            """
            SELECT
                rule_key,
                version,
                payload_json,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            FROM order_rule_overrides
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["rule_key"] or "").strip()
        if not key:
            continue
        result[key] = {
            "version": int(row["version"] or 0),
            "payload": _decode_payload(row["payload_json"]),
            "updated_by_discord_id": str(
                row["updated_by_discord_id"] or ""
            ),
            "updated_by_display_name": str(
                row["updated_by_display_name"] or ""
            ),
            "updated_at": str(row["updated_at"] or ""),
        }
    return result


def get_active_override(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    return load_active_overrides(db_file).get(str(rule_key))


def list_rule_versions(
    rule_key: str,
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = _path(db_file)
    ensure_order_rule_store(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id,
                rule_key,
                version,
                action,
                payload_json,
                source_version,
                actor_discord_id,
                actor_display_name,
                created_at
            FROM order_rule_override_versions
            WHERE rule_key = ?
            ORDER BY version DESC
            LIMIT ?
            """,
            (str(rule_key), max(1, min(int(limit or 20), 100))),
        ).fetchall()

    return [
        {
            **dict(row),
            "payload": _decode_payload(row["payload_json"]),
        }
        for row in rows
    ]


def _next_version(
    conn: sqlite3.Connection,
    rule_key: str,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version), 0)
        FROM order_rule_override_versions
        WHERE rule_key = ?
        """,
        (str(rule_key),),
    ).fetchone()
    return int((row[0] if row else 0) or 0) + 1


def publish_rule_override(
    *,
    rule_key: str,
    payload: dict[str, Any],
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    action: str = "publish",
    source_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    if not key:
        raise ValueError("缺少規則 key。")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("規則內容不能為空。")

    path = _path(db_file)
    ensure_order_rule_store(path)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        active = conn.execute(
            """
            SELECT version
            FROM order_rule_overrides
            WHERE rule_key = ?
            """,
            (key,),
        ).fetchone()
        active_version = int(active["version"] or 0) if active else 0

        if (
            expected_active_version is not None
            and int(expected_active_version) != active_version
        ):
            raise ValueError(
                "這個商品規則已被其他人更新，請重新整理後再發布。"
            )

        version = _next_version(conn, key)
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        conn.execute(
            """
            INSERT INTO order_rule_override_versions (
                rule_key,
                version,
                action,
                payload_json,
                source_version,
                actor_discord_id,
                actor_display_name,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                version,
                str(action or "publish"),
                payload_json,
                int(source_version) if source_version is not None else None,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO order_rule_overrides (
                rule_key,
                version,
                payload_json,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_key)
            DO UPDATE SET
                version = excluded.version,
                payload_json = excluded.payload_json,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = excluded.updated_at
            """,
            (
                key,
                version,
                payload_json,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.commit()

    return {
        "rule_key": key,
        "version": version,
        "payload": dict(payload),
        "action": str(action or "publish"),
        "source_version": source_version,
        "updated_at": now,
    }


def rollback_rule_override(
    *,
    rule_key: str,
    target_version: int,
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    path = _path(db_file)
    ensure_order_rule_store(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT payload_json
            FROM order_rule_override_versions
            WHERE rule_key = ?
              AND version = ?
              AND payload_json IS NOT NULL
            LIMIT 1
            """,
            (key, int(target_version)),
        ).fetchone()

    if row is None:
        raise ValueError("找不到可回復的規則版本。")

    payload = _decode_payload(row["payload_json"])
    if not payload:
        raise ValueError("該版本沒有可發布的規則內容。")

    return publish_rule_override(
        rule_key=key,
        payload=payload,
        actor_discord_id=actor_discord_id,
        actor_display_name=actor_display_name,
        expected_active_version=expected_active_version,
        action="rollback",
        source_version=int(target_version),
        db_file=path,
    )


def reset_rule_override(
    *,
    rule_key: str,
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    path = _path(db_file)
    ensure_order_rule_store(path)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        active = conn.execute(
            """
            SELECT version
            FROM order_rule_overrides
            WHERE rule_key = ?
            """,
            (key,),
        ).fetchone()
        active_version = int(active["version"] or 0) if active else 0

        if active is None:
            raise ValueError("這個商品目前沒有後台覆寫，不需要重設。")

        if (
            expected_active_version is not None
            and int(expected_active_version) != active_version
        ):
            raise ValueError(
                "這個商品規則已被其他人更新，請重新整理後再重設。"
            )

        version = _next_version(conn, key)

        conn.execute(
            """
            INSERT INTO order_rule_override_versions (
                rule_key,
                version,
                action,
                payload_json,
                source_version,
                actor_discord_id,
                actor_display_name,
                created_at
            )
            VALUES (?, ?, 'reset', NULL, ?, ?, ?, ?)
            """,
            (
                key,
                version,
                active_version,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.execute(
            "DELETE FROM order_rule_overrides WHERE rule_key = ?",
            (key,),
        )
        conn.commit()

    return {
        "rule_key": key,
        "version": version,
        "action": "reset",
        "source_version": active_version,
        "updated_at": now,
    }
