from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "credential",
    "secret",
    "token",
    "authorization",
    "cookie",
    "session",
    "account_login",
    "account_username",
    "account_password",
)


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _is_sensitive_key(key: Any) -> bool:
    text = str(key or "").strip().lower()
    return any(fragment in text for fragment in _SENSITIVE_KEY_FRAGMENTS)


def sanitize_audit_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = (
                _REDACTED
                if _is_sensitive_key(key_text)
                else sanitize_audit_payload(item)
            )
        return result

    if isinstance(value, (list, tuple, set)):
        return [sanitize_audit_payload(item) for item in value]

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def audit_json(value: Any | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        sanitize_audit_payload(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def ensure_admin_audit_table(
    db_file: str | Path | None = None,
) -> None:
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_discord_id VARCHAR(32) NOT NULL,
                action VARCHAR(100) NOT NULL,
                target_type VARCHAR(80) NOT NULL,
                target_id VARCHAR(80),
                before_json TEXT,
                after_json TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_admin
            ON admin_audit_logs(admin_discord_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_target
            ON admin_audit_logs(target_type, target_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created
            ON admin_audit_logs(created_at)
            """
        )
        conn.commit()


def admin_actor_id(admin_user: Mapping[str, Any] | None) -> str:
    user = admin_user or {}
    return str(
        user.get("id")
        or user.get("discord_id")
        or "system"
    ).strip() or "system"


def admin_actor_name(admin_user: Mapping[str, Any] | None) -> str:
    user = admin_user or {}
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "system"
    ).strip() or "system"


def write_audit_event(
    *,
    admin_user: Mapping[str, Any] | None,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    before: Any | None = None,
    after: Any | None = None,
    reason: str | None = None,
    db_file: str | Path | None = None,
) -> None:
    ensure_admin_audit_table(db_file)
    path = _db_path(db_file)

    after_payload = (
        dict(after)
        if isinstance(after, Mapping)
        else after
    )

    if reason is not None:
        if isinstance(after_payload, dict):
            after_payload.setdefault("reason", str(reason))
        elif after_payload is None:
            after_payload = {"reason": str(reason)}
        else:
            after_payload = {
                "value": after_payload,
                "reason": str(reason),
            }

    if isinstance(after_payload, dict):
        after_payload.setdefault(
            "_actor_display_name",
            admin_actor_name(admin_user),
        )

    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            INSERT INTO admin_audit_logs (
                admin_discord_id,
                action,
                target_type,
                target_id,
                before_json,
                after_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                admin_actor_id(admin_user),
                str(action)[:100],
                str(target_type)[:80],
                str(target_id)[:80] if target_id is not None else None,
                audit_json(before),
                audit_json(after_payload),
            ),
        )
        conn.commit()


def row_snapshot(
    row: Mapping[str, Any] | sqlite3.Row | None,
    *,
    fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any] | None:
    if row is None:
        return None

    data = dict(row)

    if fields is not None:
        data = {
            field: data.get(field)
            for field in fields
        }

    return sanitize_audit_payload(data)
