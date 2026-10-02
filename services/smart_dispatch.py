from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TAIPEI_TZ = timezone(timedelta(hours=8))
FIRST_EXPANSION_SECONDS = 180
FULL_EXPANSION_SECONDS = 360

DELTA_FORCE_PC_ROLE_ID = "1555430924605202493"
DELTA_FORCE_MOBILE_ROLE_ID = "1555430985732989049"
DELTA_FORCE_CATEGORY_KEYS = {"basic", "fun", "farm"}


def delta_force_platform_role_id(
    *,
    category_key: str | None,
    rule_key: str | None,
    item_label: str | None,
) -> str | None:
    category = str(category_key or "").strip().lower()
    item = str(item_label or "").strip()
    rule = str(rule_key or "").strip().lower()

    is_delta = (
        category in DELTA_FORCE_CATEGORY_KEYS
        or "三角洲" in str(category_key or "")
    )
    if not is_delta:
        return None

    is_mobile = (
        rule.startswith("basic_mobile_")
        or "〈手遊〉" in item
        or "<手遊>" in item
        or "＜手遊＞" in item
    )

    return (
        DELTA_FORCE_MOBILE_ROLE_ID
        if is_mobile
        else DELTA_FORCE_PC_ROLE_ID
    )


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_list(values) -> str:
    return json.dumps(
        [str(value) for value in (values or []) if str(value).strip()],
        ensure_ascii=False,
    )


def _load_json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item) for item in parsed if str(item).strip()]


def ensure_smart_dispatch_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS smart_dispatch_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                dispatch_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT NOT NULL,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                allowed_role_ids_json TEXT NOT NULL DEFAULT '[]',
                required_role_id TEXT,
                specified_staff_ids_json TEXT NOT NULL DEFAULT '[]',
                ranked_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                notified_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_sent_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_failed_ids_json TEXT NOT NULL DEFAULT '[]',
                stage INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                completion_reason TEXT,
                last_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_smart_dispatch_pending
                ON smart_dispatch_notifications(completed_at, stage, created_at);
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(smart_dispatch_notifications)"
            ).fetchall()
        }
        if "required_role_id" not in columns:
            conn.execute(
                "ALTER TABLE smart_dispatch_notifications "
                "ADD COLUMN required_role_id TEXT"
            )

        conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(name),),
    ).fetchone()
    return row is not None


def _parse_naive_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def get_worker_assignment_metrics(
    candidate_ids: list[str] | tuple[str, ...],
    *,
    db_file: str | Path | None = None,
    now_taipei: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    ids = [str(item) for item in candidate_ids if str(item).strip()]
    result = {
        worker_id: {
            "active_count": 0,
            "today_count": 0,
            "last_assigned_at": None,
        }
        for worker_id in ids
    }

    if not ids:
        return result

    path = _db_path(db_file)
    if not path.exists():
        return result

    now = now_taipei or _now_taipei()
    if now.tzinfo is None:
        now = now.replace(tzinfo=TAIPEI_TZ)

    start_local = now.astimezone(TAIPEI_TZ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    start_utc_naive = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    placeholders = ",".join("?" for _ in ids)

    try:
        with sqlite3.connect(path, timeout=15) as conn:
            conn.row_factory = sqlite3.Row

            if not _table_exists(conn, "order_assignments"):
                return result

            has_orders = _table_exists(conn, "web_orders")
            if has_orders:
                rows = conn.execute(
                    f"""
                    SELECT
                        a.worker_discord_id,
                        SUM(
                            CASE
                                WHEN a.is_active = 1
                                 AND o.status IN ('waiting_acceptance', 'accepted_pending_pay', 'active')
                                THEN 1 ELSE 0
                            END
                        ) AS active_count,
                        SUM(
                            CASE
                                WHEN a.assigned_at >= ?
                                THEN 1 ELSE 0
                            END
                        ) AS today_count,
                        MAX(a.assigned_at) AS last_assigned_at
                    FROM order_assignments a
                    LEFT JOIN web_orders o ON o.id = a.order_id
                    WHERE a.worker_discord_id IN ({placeholders})
                    GROUP BY a.worker_discord_id
                    """,
                    [start_utc_naive.isoformat(sep=" ", timespec="seconds"), *ids],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT
                        worker_discord_id,
                        0 AS active_count,
                        SUM(CASE WHEN assigned_at >= ? THEN 1 ELSE 0 END) AS today_count,
                        MAX(assigned_at) AS last_assigned_at
                    FROM order_assignments
                    WHERE worker_discord_id IN ({placeholders})
                    GROUP BY worker_discord_id
                    """,
                    [start_utc_naive.isoformat(sep=" ", timespec="seconds"), *ids],
                ).fetchall()

            for row in rows:
                worker_id = str(row["worker_discord_id"])
                if worker_id not in result:
                    continue
                result[worker_id] = {
                    "active_count": int(row["active_count"] or 0),
                    "today_count": int(row["today_count"] or 0),
                    "last_assigned_at": row["last_assigned_at"],
                }

            if (
                has_orders
                and _table_exists(conn, "order_acceptance_claims")
            ):
                waiting_rows = conn.execute(
                    f"""
                    SELECT
                        c.staff_discord_id,
                        COUNT(*) AS waiting_count
                    FROM order_acceptance_claims c
                    JOIN web_orders o ON o.id = c.order_id
                    WHERE c.is_active = 1
                      AND o.status = 'waiting_acceptance'
                      AND c.staff_discord_id IN ({placeholders})
                    GROUP BY c.staff_discord_id
                    """,
                    ids,
                ).fetchall()

                for row in waiting_rows:
                    worker_id = str(row["staff_discord_id"])
                    if worker_id not in result:
                        continue
                    result[worker_id]["active_count"] = (
                        int(result[worker_id].get("active_count") or 0)
                        + int(row["waiting_count"] or 0)
                    )

    except sqlite3.Error:
        return result

    return result


def rank_dispatch_candidates(
    candidate_ids: list[str] | tuple[str, ...],
    *,
    specified_staff_ids: list[str] | tuple[str, ...] | None = None,
    db_file: str | Path | None = None,
    now_taipei: datetime | None = None,
) -> list[str]:
    deduped = list(dict.fromkeys(
        str(item)
        for item in candidate_ids
        if str(item).strip()
    ))
    specified = {
        str(item)
        for item in (specified_staff_ids or [])
        if str(item).strip()
    }

    metrics = get_worker_assignment_metrics(
        deduped,
        db_file=db_file,
        now_taipei=now_taipei,
    )

    def key(worker_id: str):
        item = metrics.get(worker_id) or {}
        last = _parse_naive_utc(item.get("last_assigned_at"))

        # Never-assigned / longest-waiting staff sort first.
        last_key = (
            last.replace(tzinfo=timezone.utc).timestamp()
            if last is not None
            else 0.0
        )

        return (
            0 if worker_id in specified else 1,
            int(item.get("active_count") or 0),
            int(item.get("today_count") or 0),
            last_key,
            worker_id,
        )

    return sorted(deduped, key=key)


def notification_batch_size(required_staff_count: int) -> int:
    required = max(1, int(required_staff_count or 1))
    return max(3, min(6, required * 2))


def choose_initial_candidate_ids(
    ranked_candidate_ids: list[str] | tuple[str, ...],
    *,
    specified_staff_ids: list[str] | tuple[str, ...] | None,
    required_staff_count: int,
) -> list[str]:
    ranked = list(dict.fromkeys(str(item) for item in ranked_candidate_ids))
    specified_ordered = [
        str(item)
        for item in (specified_staff_ids or [])
        if str(item) in ranked
    ]

    result = list(dict.fromkeys(specified_ordered))
    reserved_specified_count = min(
        max(1, int(required_staff_count or 1)),
        len(
            list(
                dict.fromkeys(
                    str(item)
                    for item in (specified_staff_ids or [])
                    if str(item).strip()
                )
            )
        ),
    )
    unrestricted_slots = max(
        0,
        int(required_staff_count or 1) - reserved_specified_count,
    )

    if unrestricted_slots <= 0:
        return result

    general_limit = notification_batch_size(unrestricted_slots)
    general_added = 0

    for worker_id in ranked:
        if worker_id in result:
            continue

        result.append(worker_id)
        general_added += 1

        if general_added >= general_limit:
            break

    return result


def next_candidate_batch(
    ranked_candidate_ids: list[str] | tuple[str, ...],
    notified_candidate_ids: list[str] | tuple[str, ...],
    *,
    required_staff_count: int,
) -> list[str]:
    notified = {str(item) for item in notified_candidate_ids}
    remaining = [
        str(item)
        for item in ranked_candidate_ids
        if str(item) not in notified
    ]
    return remaining[:notification_batch_size(required_staff_count)]


def create_smart_dispatch_plan(
    *,
    order_id: int,
    dispatch_channel_id: str | int,
    dispatch_message_id: str | int,
    required_staff_count: int,
    allowed_role_ids: list[str] | tuple[str, ...],
    specified_staff_ids: list[str] | tuple[str, ...],
    ranked_candidate_ids: list[str] | tuple[str, ...],
    notified_candidate_ids: list[str] | tuple[str, ...],
    required_role_id: str | int | None = None,
    reset_existing: bool = False,
    db_file: str | Path | None = None,
) -> None:
    ensure_smart_dispatch_tables(db_file)
    now = _now_taipei().isoformat(timespec="seconds")

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        if reset_existing:
            conflict_sql = """
            ON CONFLICT(order_id)
            DO UPDATE SET
                dispatch_channel_id = excluded.dispatch_channel_id,
                dispatch_message_id = excluded.dispatch_message_id,
                required_staff_count = excluded.required_staff_count,
                allowed_role_ids_json = excluded.allowed_role_ids_json,
                required_role_id = excluded.required_role_id,
                specified_staff_ids_json = excluded.specified_staff_ids_json,
                ranked_candidate_ids_json = excluded.ranked_candidate_ids_json,
                notified_candidate_ids_json = excluded.notified_candidate_ids_json,
                specified_dm_sent_ids_json = '[]',
                specified_dm_failed_ids_json = '[]',
                stage = 0,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                completed_at = NULL,
                completion_reason = NULL,
                last_error = NULL
            """
        else:
            conflict_sql = "ON CONFLICT(order_id) DO NOTHING"

        conn.execute(
            f"""
            INSERT INTO smart_dispatch_notifications (
                order_id,
                dispatch_channel_id,
                dispatch_message_id,
                required_staff_count,
                allowed_role_ids_json,
                required_role_id,
                specified_staff_ids_json,
                ranked_candidate_ids_json,
                notified_candidate_ids_json,
                stage,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            {conflict_sql}
            """,
            (
                int(order_id),
                str(dispatch_channel_id),
                str(dispatch_message_id),
                max(1, int(required_staff_count or 1)),
                _json_list(allowed_role_ids),
                str(required_role_id) if required_role_id is not None else None,
                _json_list(specified_staff_ids),
                _json_list(ranked_candidate_ids),
                _json_list(notified_candidate_ids),
                now,
                now,
            ),
        )
        conn.commit()


def _row_to_plan(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in (
        "allowed_role_ids_json",
        "specified_staff_ids_json",
        "ranked_candidate_ids_json",
        "notified_candidate_ids_json",
        "specified_dm_sent_ids_json",
        "specified_dm_failed_ids_json",
    ):
        data[key.removesuffix("_json")] = _load_json_list(data.get(key))
    return data


def get_smart_dispatch_plan(
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_smart_dispatch_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM smart_dispatch_notifications
            WHERE order_id = ?
            LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()

        return _row_to_plan(row) if row is not None else None


def list_pending_smart_dispatch_plans(
    *,
    db_file: str | Path | None = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    ensure_smart_dispatch_tables(db_file)
    safe_limit = max(1, min(int(limit or 300), 1000))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM smart_dispatch_notifications
            WHERE completed_at IS NULL
              AND stage < 2
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_row_to_plan(row) for row in rows]


def mark_smart_dispatch_stage(
    order_id: int,
    *,
    stage: int,
    newly_notified_ids: list[str] | tuple[str, ...] | None = None,
    last_error: str | None = None,
    db_file: str | Path | None = None,
) -> None:
    ensure_smart_dispatch_tables(db_file)
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT notified_candidate_ids_json
            FROM smart_dispatch_notifications
            WHERE order_id = ?
            LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()

        notified = _load_json_list(
            row["notified_candidate_ids_json"]
            if row is not None
            else "[]"
        )
        notified = list(dict.fromkeys(
            [*notified, *[str(item) for item in (newly_notified_ids or [])]]
        ))
        now = _now_taipei().isoformat(timespec="seconds")

        conn.execute(
            """
            UPDATE smart_dispatch_notifications
            SET stage = CASE WHEN stage < ? THEN ? ELSE stage END,
                notified_candidate_ids_json = ?,
                last_error = ?,
                updated_at = ?
            WHERE order_id = ?
            """,
            (
                int(stage),
                int(stage),
                _json_list(notified),
                str(last_error)[:1000] if last_error else None,
                now,
                int(order_id),
            ),
        )
        conn.commit()


def set_specified_dm_results(
    order_id: int,
    *,
    sent_ids: list[str] | tuple[str, ...],
    failed_ids: list[str] | tuple[str, ...],
    db_file: str | Path | None = None,
) -> None:
    ensure_smart_dispatch_tables(db_file)
    now = _now_taipei().isoformat(timespec="seconds")

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE smart_dispatch_notifications
            SET specified_dm_sent_ids_json = ?,
                specified_dm_failed_ids_json = ?,
                updated_at = ?
            WHERE order_id = ?
            """,
            (
                _json_list(sent_ids),
                _json_list(failed_ids),
                now,
                int(order_id),
            ),
        )
        conn.commit()


def complete_smart_dispatch_plan(
    order_id: int,
    *,
    reason: str,
    db_file: str | Path | None = None,
) -> None:
    ensure_smart_dispatch_tables(db_file)
    now = _now_taipei().isoformat(timespec="seconds")

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE smart_dispatch_notifications
            SET stage = 2,
                completed_at = COALESCE(completed_at, ?),
                completion_reason = ?,
                updated_at = ?
            WHERE order_id = ?
            """,
            (
                now,
                str(reason or "completed")[:200],
                now,
                int(order_id),
            ),
        )
        conn.commit()


def plan_age_seconds(plan: dict[str, Any], *, now: datetime | None = None) -> int:
    created_text = str(plan.get("created_at") or "").strip()
    if not created_text:
        return 0

    try:
        created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
    except ValueError:
        return 0

    if created.tzinfo is None:
        created = created.replace(tzinfo=TAIPEI_TZ)

    current = now or _now_taipei()
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)

    return max(0, int((current.astimezone(TAIPEI_TZ) - created.astimezone(TAIPEI_TZ)).total_seconds()))
