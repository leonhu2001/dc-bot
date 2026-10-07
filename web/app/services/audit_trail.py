from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


REDACTED = "[已遮罩]"

_SENSITIVE_EXACT_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "credential",
    "credentials",
    "account_password",
    "game_password",
    "login_password",
    "payment_reference",
    "payment_proof",
    "proof_url",
    "screenshot_url",
    "attachment_url",
    "attachments",
    "bank_account",
    "bank_account_no",
    "card_number",
    "cvv",
}

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "payment_proof",
    "proof_image",
    "account_number",
    "card_number",
)


def _default_web_db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def is_sensitive_audit_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower()

    if normalized in _SENSITIVE_EXACT_KEYS:
        return True

    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_audit_payload(value: Any, *, key: str | None = None) -> Any:
    if key is not None and is_sensitive_audit_key(key):
        return REDACTED if value not in (None, "", [], {}) else value

    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_audit_payload(
                item_value,
                key=str(item_key),
            )
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_audit_payload(item)
            for item in value
        ]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def audit_changes(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    before_data = sanitize_audit_payload(dict(before or {}))
    after_data = sanitize_audit_payload(dict(after or {}))

    keys = set(before_data) | set(after_data)
    result: dict[str, dict[str, Any]] = {}

    for key in sorted(keys):
        old = before_data.get(key)
        new = after_data.get(key)

        if old == new:
            continue

        result[key] = {
            "before": old,
            "after": new,
        }

    return result


def _json_text(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(
        sanitize_audit_payload(value),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def ensure_audit_table(db_file: str | Path | None = None) -> None:
    path = Path(db_file) if db_file is not None else _default_web_db_path()

    with sqlite3.connect(path, timeout=15) as conn:
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
                created_at DATETIME NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_admin_discord_id
            ON admin_audit_logs(admin_discord_id)
            """
        )
        conn.commit()


def _run_post_audit_hooks(
    *,
    action: str,
    target_type: str,
    target_id: str | int | None,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    db_file: str | Path,
) -> None:
    """Run non-transactional side effects after an audit row is committed.

    A notification failure must never roll back or disguise a completed salary
    state change, so hooks are intentionally best-effort and isolated here.
    """
    if str(action) != "set_person_payout_status":
        return
    if str(target_type) != "payout_person":
        return

    try:
        from web.app.services.payout_notifications import (
            send_payout_paid_notification,
        )

        result = send_payout_paid_notification(
            db_file=db_file,
            person_id=target_id,
            before=before,
            after=after,
        )
        if result.get("sent"):
            print(
                "[payout_notification] sent",
                "person=", str(target_id or ""),
                "total=", result.get("total", 0),
            )
    except Exception as exc:
        print(
            "[payout_notification] delivery failed:",
            repr(exc),
        )


def write_sqlite_audit_log(
    *,
    admin_discord_id: str | int,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    db_file: str | Path | None = None,
) -> int:
    path = Path(db_file) if db_file is not None else _default_web_db_path()
    ensure_audit_table(path)

    before_payload = dict(before or {}) if before is not None else None
    after_payload = dict(after or {}) if after is not None else None

    if reason is not None or metadata:
        if after_payload is None:
            after_payload = {}

        if reason is not None:
            after_payload["reason"] = str(reason)

        if metadata:
            after_payload["_audit_meta"] = dict(metadata)

    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(admin_discord_id),
                str(action),
                str(target_type),
                str(target_id) if target_id is not None else None,
                _json_text(before_payload),
                _json_text(after_payload),
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"),
            ),
        )
        conn.commit()
        audit_id = int(cur.lastrowid)

    _run_post_audit_hooks(
        action=str(action),
        target_type=str(target_type),
        target_id=target_id,
        before=before_payload,
        after=after_payload,
        db_file=path,
    )

    return audit_id


def audit_snapshot(
    value: Mapping[str, Any] | sqlite3.Row | None,
    *,
    include: set[str] | tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None

    data = dict(value)

    if include is not None:
        allowed = {str(item) for item in include}
        data = {
            key: item
            for key, item in data.items()
            if key in allowed
        }

    return sanitize_audit_payload(data)
