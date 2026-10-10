from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.vip_levels import (
    BASE_MEMBER_LEVELS,
    VIP_RETENTION_DAYS,
    get_vip_retention_days,
    has_active_vip_progress_reset,
)

TAIPEI_TZ = timezone(timedelta(hours=8))


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _member_index_from_total(total_spent: int) -> int:
    index = 0
    for i, level in enumerate(BASE_MEMBER_LEVELS):
        if int(total_spent or 0) >= int(level["threshold"]):
            index = i
        else:
            break
    return index


def effective_vip_index_from_data(data: dict[str, Any]) -> int:
    total_spent = max(0, _safe_int(data.get("total_spent"), 0))
    cumulative_index = _member_index_from_total(total_spent)

    raw_stored = data.get("vip_level_index")
    if raw_stored in (None, ""):
        return cumulative_index

    stored_index = max(
        0,
        min(_safe_int(raw_stored, cumulative_index), len(BASE_MEMBER_LEVELS) - 1),
    )

    if stored_index < cumulative_index and has_active_vip_progress_reset(data):
        base_total = max(0, _safe_int(data.get("vip_progress_base_total_spent"), 0))
        earned_after_reset = max(0, total_spent - base_total)
        virtual_total = int(BASE_MEMBER_LEVELS[stored_index]["threshold"]) + earned_after_reset
        progressed_index = _member_index_from_total(virtual_total)
        return max(stored_index, min(progressed_index, len(BASE_MEMBER_LEVELS) - 1))

    if stored_index < cumulative_index:
        return cumulative_index

    return stored_index


def ensure_vip_review_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vip_review_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_level_index INTEGER,
                extend_days INTEGER,
                reason TEXT NOT NULL,
                operator_discord_id TEXT NOT NULL,
                operator_display_name TEXT,
                operator_is_manager INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS ix_vip_review_actions_status
            ON vip_review_actions(status, id);

            CREATE TABLE IF NOT EXISTS vip_review_protections (
                customer_id TEXT PRIMARY KEY,
                protected_until TEXT NOT NULL,
                reason TEXT,
                updated_by_discord_id TEXT,
                updated_by_display_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vip_review_notifications (
                customer_id TEXT PRIMARY KEY,
                due_key TEXT NOT NULL,
                last_notified_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vip_review_digest_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_digest_date TEXT,
                updated_at TEXT
            );
            """
        )
        conn.commit()


def get_protection_map(db_file: str | Path | None = None) -> dict[str, dict[str, Any]]:
    ensure_vip_review_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM vip_review_protections"
        ).fetchall()
    return {str(row["customer_id"]): dict(row) for row in rows}


def get_vip_protection(customer_id: str | int, db_file: str | Path | None = None) -> dict[str, Any] | None:
    ensure_vip_review_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM vip_review_protections WHERE customer_id = ? LIMIT 1",
            (str(customer_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def set_vip_protection(
    customer_id: str | int,
    protected_until: datetime | str,
    *,
    reason: str,
    operator_discord_id: str | int,
    operator_display_name: str | None = None,
    db_file: str | Path | None = None,
) -> None:
    ensure_vip_review_tables(db_file)
    path = _db_path(db_file)
    if isinstance(protected_until, datetime):
        protected_until_text = protected_until.astimezone(TAIPEI_TZ).isoformat(timespec="seconds")
    else:
        parsed = _parse_datetime(protected_until)
        if parsed is None:
            raise ValueError("無效的 VIP 保護到期日")
        protected_until_text = parsed.isoformat(timespec="seconds")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            INSERT INTO vip_review_protections (
                customer_id,
                protected_until,
                reason,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                protected_until = excluded.protected_until,
                reason = excluded.reason,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = excluded.updated_at
            """,
            (
                str(customer_id),
                protected_until_text,
                str(reason or "").strip(),
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                _now_iso(),
            ),
        )
        conn.commit()


def clear_vip_protection(customer_id: str | int, db_file: str | Path | None = None) -> None:
    ensure_vip_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            "DELETE FROM vip_review_protections WHERE customer_id = ?",
            (str(customer_id),),
        )
        conn.commit()


def build_vip_retention_status(
    data: dict[str, Any],
    *,
    protection_until: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (now or _now()).astimezone(TAIPEI_TZ)
    current_index = effective_vip_index_from_data(data)
    cumulative_index = _member_index_from_total(max(0, _safe_int(data.get("total_spent"), 0)))
    current_level = BASE_MEMBER_LEVELS[current_index]
    level_name = str(current_level["name"])
    retention_days = get_vip_retention_days(level_name)

    last_order_at = _parse_datetime(data.get("last_order_at"))
    manual_anchor = _parse_datetime(data.get("last_level_manual_fixed_at"))
    anchor_candidates = [value for value in (last_order_at, manual_anchor) if value is not None]
    retention_anchor = max(anchor_candidates) if anchor_candidates else None

    base_expiry = (
        retention_anchor + timedelta(days=retention_days)
        if retention_anchor is not None and retention_days > 0
        else None
    )
    protection_dt = _parse_datetime(protection_until)
    effective_expiry = base_expiry
    if protection_dt is not None and (
        effective_expiry is None or protection_dt > effective_expiry
    ):
        effective_expiry = protection_dt

    is_due = bool(
        current_index > 0
        and effective_expiry is not None
        and current_time >= effective_expiry
    )

    days_since_purchase = None
    if last_order_at is not None:
        days_since_purchase = max(0, (current_time.date() - last_order_at.date()).days)

    days_remaining = None
    days_overdue = 0
    if effective_expiry is not None:
        delta_seconds = (effective_expiry - current_time).total_seconds()
        if delta_seconds >= 0:
            days_remaining = max(0, math.ceil(delta_seconds / 86400))
        else:
            days_remaining = 0
            days_overdue = max(1, math.ceil(abs(delta_seconds) / 86400))

    due_key = ""
    if is_due and effective_expiry is not None:
        due_key = f"{current_index}:{effective_expiry.isoformat(timespec='seconds')}"

    return {
        "current_index": current_index,
        "current_level": level_name,
        "cumulative_index": cumulative_index,
        "cumulative_level": str(BASE_MEMBER_LEVELS[cumulative_index]["name"]),
        "suggested_index": max(0, current_index - 1),
        "suggested_level": str(BASE_MEMBER_LEVELS[max(0, current_index - 1)]["name"]),
        "retention_days": retention_days,
        "last_order_at": last_order_at.isoformat(timespec="seconds") if last_order_at else None,
        "retention_anchor_at": retention_anchor.isoformat(timespec="seconds") if retention_anchor else None,
        "base_expiry_at": base_expiry.isoformat(timespec="seconds") if base_expiry else None,
        "protection_until": protection_dt.isoformat(timespec="seconds") if protection_dt else None,
        "expiry_at": effective_expiry.isoformat(timespec="seconds") if effective_expiry else None,
        "days_since_purchase": days_since_purchase,
        "days_remaining": days_remaining,
        "days_overdue": days_overdue,
        "is_due": is_due,
        "due_key": due_key,
    }


def _load_customer_rows(db_file: str | Path | None = None) -> list[dict[str, Any]]:
    path = _db_path(db_file)
    if not path.exists():
        return []

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers' LIMIT 1"
        ).fetchone()
        if table_exists is None:
            return []

        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(customers)").fetchall()}
        id_column = "customer_id" if "customer_id" in columns else "user_id" if "user_id" in columns else None
        if id_column is None:
            return []

        rows = conn.execute("SELECT * FROM customers").fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        customer_id = str(item.get(id_column) or "").strip()
        if not customer_id:
            continue

        raw_data = item.get("data_json") if "data_json" in item else item.get("data")
        data: dict[str, Any] = {}
        if isinstance(raw_data, str) and raw_data.strip():
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}

        if "total_spent" in item and item.get("total_spent") is not None:
            data["total_spent"] = _safe_int(item.get("total_spent"), _safe_int(data.get("total_spent"), 0))
        if "last_order_at" in item and item.get("last_order_at"):
            data["last_order_at"] = item.get("last_order_at")
        if "level" in item and item.get("level") and data.get("vip_level_index") in (None, ""):
            level_text = str(item.get("level"))
            for index, level in enumerate(BASE_MEMBER_LEVELS):
                if str(level["name"]) == level_text:
                    data["vip_level_index"] = index
                    break

        result.append({"customer_id": customer_id, "data": data})

    return result


def build_vip_review_snapshot(
    *,
    db_file: str | Path | None = None,
    view: str = "vip",
    now: datetime | None = None,
) -> dict[str, Any]:
    safe_view = str(view or "vip").strip().lower()
    if safe_view not in {"vip", "pending", "all"}:
        safe_view = "vip"

    protections = get_protection_map(db_file)
    all_rows: list[dict[str, Any]] = []
    for item in _load_customer_rows(db_file):
        customer_id = str(item["customer_id"])
        data = dict(item["data"])
        protection = protections.get(customer_id) or {}
        status = build_vip_retention_status(
            data,
            protection_until=protection.get("protected_until"),
            now=now,
        )
        row = {
            "customer_id": customer_id,
            "total_spent": max(0, _safe_int(data.get("total_spent"), 0)),
            "last_order_at": status["last_order_at"],
            "last_manual_reason": str(data.get("last_level_manual_fixed_reason") or "").strip(),
            "last_manual_by": str(data.get("last_level_manual_fixed_by") or "").strip(),
            **status,
        }
        all_rows.append(row)

    vip_rows = [row for row in all_rows if int(row["current_index"]) > 0]
    pending_rows = [row for row in vip_rows if bool(row["is_due"])]

    if safe_view == "pending":
        rows = pending_rows
    elif safe_view == "all":
        rows = all_rows
    else:
        rows = vip_rows

    rows.sort(
        key=lambda row: (
            0 if row["is_due"] else 1,
            -int(row["days_overdue"] or 0),
            -int(row["current_index"] or 0),
            str(row["customer_id"]),
        )
    )

    level_counts = {
        str(level["name"]): 0
        for level in BASE_MEMBER_LEVELS[1:]
    }
    for row in vip_rows:
        level_counts[str(row["current_level"])] = level_counts.get(str(row["current_level"]), 0) + 1

    return {
        "rows": rows,
        "stats": {
            "vip_count": len(vip_rows),
            "pending_count": len(pending_rows),
            "unknown_last_order_count": sum(1 for row in vip_rows if not row.get("last_order_at")),
            "level_counts": level_counts,
        },
        "view": safe_view,
        "levels": [
            {
                "index": index,
                "name": str(level["name"]),
                "retention_days": int(VIP_RETENTION_DAYS.get(str(level["name"]), 0)),
            }
            for index, level in enumerate(BASE_MEMBER_LEVELS)
        ],
    }


def queue_vip_review_action(
    *,
    customer_id: str | int,
    action: str,
    reason: str,
    operator_discord_id: str | int,
    operator_display_name: str | None,
    operator_is_manager: bool,
    target_level_index: int | None = None,
    extend_days: int | None = None,
    db_file: str | Path | None = None,
) -> int:
    ensure_vip_review_tables(db_file)
    action_text = str(action or "").strip().lower()
    if action_text not in {"set_level", "extend"}:
        raise ValueError("不支援的 VIP 操作")

    reason_text = str(reason or "").strip()
    if not reason_text:
        raise ValueError("請填寫調整原因")

    target = None
    days = None
    if action_text == "set_level":
        target = _safe_int(target_level_index, -1)
        if target < 0 or target >= len(BASE_MEMBER_LEVELS):
            raise ValueError("VIP 階級無效")
    else:
        days = _safe_int(extend_days, 0)
        max_days = 365 if operator_is_manager else 30
        if days < 1 or days > max_days:
            raise ValueError(f"延長天數需為 1～{max_days} 天")

    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT INTO vip_review_actions (
                customer_id,
                action,
                target_level_index,
                extend_days,
                reason,
                operator_discord_id,
                operator_display_name,
                operator_is_manager,
                status,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                str(customer_id),
                action_text,
                target,
                days,
                reason_text,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                1 if operator_is_manager else 0,
                _now_iso(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def claim_pending_vip_review_actions(
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_vip_review_tables(db_file)
    safe_limit = max(1, min(_safe_int(limit, 20), 100))
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE vip_review_actions
            SET status = 'pending', error_message = NULL
            WHERE status = 'processing'
              AND processed_at IS NOT NULL
              AND processed_at <= datetime('now', '-10 minutes')
            """
        )
        rows = conn.execute(
            """
            SELECT * FROM vip_review_actions
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""
                UPDATE vip_review_actions
                SET status = 'processing', processed_at = ?
                WHERE status = 'pending' AND id IN ({placeholders})
                """,
                [_now_iso(), *ids],
            )
        conn.commit()
        return [dict(row) for row in rows]


def mark_vip_review_action_done(action_id: int, db_file: str | Path | None = None) -> None:
    ensure_vip_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE vip_review_actions
            SET status = 'done', error_message = NULL, processed_at = ?
            WHERE id = ?
            """,
            (_now_iso(), int(action_id)),
        )
        conn.commit()


def mark_vip_review_action_failed(
    action_id: int,
    error_message: str,
    db_file: str | Path | None = None,
) -> None:
    ensure_vip_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE vip_review_actions
            SET status = 'failed', error_message = ?, processed_at = ?
            WHERE id = ?
            """,
            (str(error_message or "")[:1000], _now_iso(), int(action_id)),
        )
        conn.commit()


def list_new_due_notifications(
    pending_rows: list[dict[str, Any]],
    *,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_vip_review_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        sent = {
            str(row["customer_id"]): str(row["due_key"])
            for row in conn.execute(
                "SELECT customer_id, due_key FROM vip_review_notifications"
            ).fetchall()
        }
    return [
        row for row in pending_rows
        if str(row.get("due_key") or "")
        and sent.get(str(row.get("customer_id") or "")) != str(row.get("due_key") or "")
    ]


def mark_due_notifications_sent(
    rows: list[dict[str, Any]],
    *,
    db_file: str | Path | None = None,
) -> None:
    if not rows:
        return
    ensure_vip_review_tables(db_file)
    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO vip_review_notifications (customer_id, due_key, last_notified_at)
                VALUES (?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    due_key = excluded.due_key,
                    last_notified_at = excluded.last_notified_at
                """,
                (
                    str(row.get("customer_id") or ""),
                    str(row.get("due_key") or ""),
                    now_text,
                ),
            )
        conn.commit()


def get_last_digest_date(db_file: str | Path | None = None) -> str:
    ensure_vip_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        row = conn.execute(
            "SELECT last_digest_date FROM vip_review_digest_state WHERE id = 1"
        ).fetchone()
    return str(row[0] or "") if row else ""


def mark_digest_sent(date_text: str, db_file: str | Path | None = None) -> None:
    ensure_vip_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            INSERT INTO vip_review_digest_state (id, last_digest_date, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_digest_date = excluded.last_digest_date,
                updated_at = excluded.updated_at
            """,
            (str(date_text), _now_iso()),
        )
        conn.commit()
