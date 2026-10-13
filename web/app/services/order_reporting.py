from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import httpx
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.engine import Engine

from shared.db import SessionLocal, engine
from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    SyncEventType,
    WebOrder,
    WorkerPayout,
)
from web.app.config import config
from web.app.services.order_service import create_sync_event, recalculate_order_payouts


REPORT_STATUS_MISSING = "missing"
REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_CHANGES_REQUESTED = "changes_requested"
REPORT_STATUS_APPROVED = "approved"
REPORT_STATUSES = {
    REPORT_STATUS_MISSING,
    REPORT_STATUS_PENDING,
    REPORT_STATUS_CHANGES_REQUESTED,
    REPORT_STATUS_APPROVED,
}

TAIPEI_TZ = timezone(timedelta(hours=8))
REPORT_NOTE_MAX_LENGTH = 1000
REVIEW_NOTE_MAX_LENGTH = 1000
REMINDER_MAX_ATTEMPTS = 3
REMINDER_LOOP_SECONDS = 30

metadata = MetaData()

order_reports = Table(
    "order_reports",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, nullable=False, unique=True, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column("is_legacy", Integer, nullable=False, default=0),
    Column("streamed", Integer, nullable=True),
    Column("recording_saved", Integer, nullable=True),
    Column("recording_holder", String(120), nullable=True),
    Column("note", Text, nullable=True),
    Column("submitted_by_discord_id", String(32), nullable=True),
    Column("submitted_by_display_name", String(120), nullable=True),
    Column("submitted_at", DateTime, nullable=True),
    Column("reviewed_by_discord_id", String(32), nullable=True),
    Column("reviewed_by_display_name", String(120), nullable=True),
    Column("reviewed_at", DateTime, nullable=True),
    Column("review_note", Text, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

order_report_workers = Table(
    "order_report_workers",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, nullable=False, index=True),
    Column("worker_discord_id", String(32), nullable=False),
    Column("worker_display_name", String(120), nullable=True),
    Column("has_named_bonus", Integer, nullable=False, default=0),
    UniqueConstraint(
        "report_id",
        "worker_discord_id",
        name="uq_order_report_worker",
    ),
)

order_report_audit = Table(
    "order_report_audit",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, nullable=False, index=True),
    Column("action", String(64), nullable=False),
    Column("actor_discord_id", String(32), nullable=True),
    Column("actor_display_name", String(120), nullable=True),
    Column("before_json", Text, nullable=True),
    Column("after_json", Text, nullable=True),
    Column("note", Text, nullable=True),
    Column("created_at", DateTime, nullable=False),
)

order_report_reminders = Table(
    "order_report_reminders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, nullable=False, index=True),
    Column("worker_discord_id", String(32), nullable=False),
    Column("status", String(24), nullable=False, default="pending", index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text, nullable=True),
    Column("sent_at", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint(
        "order_id",
        "worker_discord_id",
        name="uq_order_report_reminder_worker",
    ),
)


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)


def _display_name(user: Mapping[str, Any] | None) -> str:
    user = user or {}
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


def _to_bool_int(value: bool | int | str | None) -> int:
    if isinstance(value, bool):
        return int(value)
    return 1 if str(value or "").strip().lower() in {"1", "true", "yes", "on"} else 0


def _trimmed(value: Any, limit: int) -> str | None:
    result = str(value or "").strip()
    return result[:limit] or None


def _mapping(row) -> dict | None:
    return dict(row) if row is not None else None


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _status_label(status: str | None) -> str:
    return {
        REPORT_STATUS_MISSING: "未報單",
        REPORT_STATUS_PENDING: "待審核",
        REPORT_STATUS_CHANGES_REQUESTED: "需修改",
        REPORT_STATUS_APPROVED: "已報單",
    }.get(str(status or ""), "未報單")


def _public_base_url() -> str:
    allowed = tuple(config.WEB_ALLOWED_ORIGINS or ())
    if allowed:
        return str(allowed[0]).rstrip("/")
    return "https://mowanentertainment.com"


def _install_sqlite_triggers(bind: Engine) -> None:
    if getattr(bind.dialect, "name", "") != "sqlite":
        return

    with bind.begin() as conn:
        for trigger_name in (
            "trg_order_report_after_close",
            "trg_order_report_after_closed_insert",
            "trg_order_report_assignment_insert",
            "trg_order_report_assignment_activate",
        ):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))

        conn.execute(text("""
            CREATE TRIGGER trg_order_report_after_close
            AFTER UPDATE OF status ON web_orders
            WHEN LOWER(TRIM(COALESCE(NEW.status, ''))) = 'closed'
             AND LOWER(TRIM(COALESCE(OLD.status, ''))) != 'closed'
            BEGIN
                INSERT OR IGNORE INTO order_reports (
                    order_id,
                    status,
                    is_legacy,
                    created_at,
                    updated_at
                ) VALUES (
                    NEW.id,
                    'missing',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO order_report_reminders (
                    order_id,
                    worker_discord_id,
                    status,
                    attempts,
                    created_at,
                    updated_at
                )
                SELECT
                    NEW.id,
                    a.worker_discord_id,
                    'pending',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM order_assignments a
                WHERE a.order_id = NEW.id
                  AND COALESCE(a.is_active, 0) = 1;
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER trg_order_report_after_closed_insert
            AFTER INSERT ON web_orders
            WHEN LOWER(TRIM(COALESCE(NEW.status, ''))) = 'closed'
            BEGIN
                INSERT OR IGNORE INTO order_reports (
                    order_id,
                    status,
                    is_legacy,
                    created_at,
                    updated_at
                ) VALUES (
                    NEW.id,
                    'missing',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER trg_order_report_assignment_insert
            AFTER INSERT ON order_assignments
            WHEN COALESCE(NEW.is_active, 0) = 1
             AND EXISTS (
                SELECT 1
                FROM order_reports r
                WHERE r.order_id = NEW.order_id
                  AND r.status = 'missing'
                  AND COALESCE(r.is_legacy, 0) = 0
             )
            BEGIN
                INSERT OR IGNORE INTO order_report_reminders (
                    order_id,
                    worker_discord_id,
                    status,
                    attempts,
                    created_at,
                    updated_at
                ) VALUES (
                    NEW.order_id,
                    NEW.worker_discord_id,
                    'pending',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER trg_order_report_assignment_activate
            AFTER UPDATE OF is_active ON order_assignments
            WHEN COALESCE(NEW.is_active, 0) = 1
             AND COALESCE(OLD.is_active, 0) != 1
             AND EXISTS (
                SELECT 1
                FROM order_reports r
                WHERE r.order_id = NEW.order_id
                  AND r.status = 'missing'
                  AND COALESCE(r.is_legacy, 0) = 0
             )
            BEGIN
                INSERT OR IGNORE INTO order_report_reminders (
                    order_id,
                    worker_discord_id,
                    status,
                    attempts,
                    created_at,
                    updated_at
                ) VALUES (
                    NEW.order_id,
                    NEW.worker_discord_id,
                    'pending',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );
            END
        """))


def ensure_order_reporting_tables(bind: Engine = engine) -> None:
    """Create report tables and establish the new-system cutoff safely.

    Existing closed orders are inserted as approved before the close triggers are
    installed. Once the trigger exists, only a *new* transition into closed gets
    the missing-report state. This makes deployment idempotent and means old
    orders never suddenly become overdue reports.
    """
    metadata.create_all(bind=bind)

    now = _now()
    with bind.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO order_reports (
                    order_id,
                    status,
                    is_legacy,
                    review_note,
                    created_at,
                    updated_at,
                    reviewed_at
                )
                SELECT
                    o.id,
                    'approved',
                    1,
                    '舊制訂單，系統視為已報單。',
                    COALESCE(o.closed_at, o.updated_at, o.created_at, :now),
                    COALESCE(o.closed_at, o.updated_at, o.created_at, :now),
                    COALESCE(o.closed_at, o.updated_at, o.created_at, :now)
                FROM web_orders o
                WHERE LOWER(TRIM(COALESCE(o.status, ''))) = 'closed'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM order_reports r
                      WHERE r.order_id = o.id
                  )
            """),
            {"now": now},
        )

        # Recover reminder jobs if the web process died while one was claimed.
        conn.execute(
            text("""
                UPDATE order_report_reminders
                SET status = 'pending',
                    updated_at = :now
                WHERE status = 'processing'
                  AND updated_at < :stale_before
            """),
            {
                "now": now,
                "stale_before": now - timedelta(minutes=10),
            },
        )

    _install_sqlite_triggers(bind)


def _queue_missing_reminders(conn, order_id: int) -> None:
    rows = conn.execute(
        text("""
            SELECT worker_discord_id
            FROM order_assignments
            WHERE order_id = :order_id
              AND COALESCE(is_active, 0) = 1
        """),
        {"order_id": int(order_id)},
    ).fetchall()
    now = _now()

    for row in rows:
        worker_id = str(row[0] or "").strip()
        if not worker_id:
            continue
        exists = conn.execute(
            text("""
                SELECT id
                FROM order_report_reminders
                WHERE order_id = :order_id
                  AND worker_discord_id = :worker_id
                LIMIT 1
            """),
            {"order_id": int(order_id), "worker_id": worker_id},
        ).first()
        if exists is None:
            conn.execute(
                order_report_reminders.insert().values(
                    order_id=int(order_id),
                    worker_discord_id=worker_id,
                    status="pending",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )


def list_reports_for_user(
    worker_discord_id: str,
    *,
    status_filter: str | None = None,
    keyword: str | None = None,
    limit: int = 150,
) -> list[dict]:
    ensure_order_reporting_tables()
    worker_id = str(worker_discord_id or "").strip()
    if not worker_id:
        return []

    where_status = ""
    params: dict[str, Any] = {
        "worker_id": worker_id,
        "limit": max(1, min(int(limit), 300)),
    }
    if status_filter in REPORT_STATUSES:
        where_status = " AND COALESCE(r.status, 'approved') = :status_filter"
        params["status_filter"] = status_filter

    where_keyword = ""
    keyword_text = str(keyword or "").strip()
    if keyword_text:
        where_keyword = """
            AND (
                COALESCE(o.bot_order_no, '') LIKE :keyword
                OR COALESCE(o.customer_display_name, '') LIKE :keyword
                OR COALESCE(o.item, '') LIKE :keyword
                OR COALESCE(o.category, '') LIKE :keyword
            )
        """
        params["keyword"] = f"%{keyword_text}%"

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT
                    o.id,
                    o.bot_order_no,
                    o.customer_display_name,
                    o.category,
                    o.item,
                    o.closed_at,
                    o.updated_at,
                    COALESCE(r.status, 'approved') AS report_status,
                    COALESCE(r.is_legacy, 1) AS is_legacy,
                    r.submitted_by_display_name,
                    r.submitted_at,
                    r.review_note
                FROM web_orders o
                JOIN order_assignments a
                  ON a.order_id = o.id
                 AND a.worker_discord_id = :worker_id
                 AND COALESCE(a.is_active, 0) = 1
                LEFT JOIN order_reports r ON r.order_id = o.id
                WHERE LOWER(TRIM(COALESCE(o.status, ''))) = 'closed'
                """
                + where_status
                + where_keyword
                + """
                ORDER BY COALESCE(o.closed_at, o.updated_at, o.created_at) DESC, o.id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    return [dict(row) for row in rows]


def list_reports_for_review(
    *,
    status_filter: str | None = None,
    keyword: str | None = None,
    limit: int = 250,
) -> list[dict]:
    ensure_order_reporting_tables()
    where_status = ""
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}

    if status_filter in REPORT_STATUSES:
        where_status = " AND COALESCE(r.status, 'approved') = :status_filter"
        params["status_filter"] = status_filter
    elif status_filter in {None, "", "actionable"}:
        where_status = " AND COALESCE(r.status, 'approved') IN ('missing','pending','changes_requested')"

    where_keyword = ""
    keyword_text = str(keyword or "").strip()
    if keyword_text:
        where_keyword = """
            AND (
                COALESCE(o.bot_order_no, '') LIKE :keyword
                OR COALESCE(o.customer_display_name, '') LIKE :keyword
                OR COALESCE(o.item, '') LIKE :keyword
                OR EXISTS (
                    SELECT 1
                    FROM order_assignments a2
                    WHERE a2.order_id = o.id
                      AND COALESCE(a2.worker_display_name, '') LIKE :keyword
                )
            )
        """
        params["keyword"] = f"%{keyword_text}%"

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    o.id,
                    o.bot_order_no,
                    o.customer_display_name,
                    o.category,
                    o.item,
                    o.closed_at,
                    o.updated_at,
                    COALESCE(r.status, 'approved') AS report_status,
                    COALESCE(r.is_legacy, 1) AS is_legacy,
                    r.submitted_by_display_name,
                    r.submitted_at,
                    r.review_note,
                    (
                        SELECT GROUP_CONCAT(COALESCE(a.worker_display_name, a.worker_discord_id), '、')
                        FROM order_assignments a
                        WHERE a.order_id = o.id
                          AND COALESCE(a.is_active, 0) = 1
                    ) AS worker_names
                FROM web_orders o
                LEFT JOIN order_reports r ON r.order_id = o.id
                WHERE LOWER(TRIM(COALESCE(o.status, ''))) = 'closed'
                """
                + where_status
                + where_keyword
                + """
                ORDER BY
                    CASE COALESCE(r.status, 'approved')
                        WHEN 'missing' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'changes_requested' THEN 2
                        ELSE 3
                    END,
                    COALESCE(o.closed_at, o.updated_at, o.created_at) DESC,
                    o.id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    return [dict(row) for row in rows]


def _load_report_detail(order_id: int) -> dict | None:
    ensure_order_reporting_tables()
    with engine.begin() as conn:
        order = conn.execute(
            text("""
                SELECT
                    o.id,
                    o.bot_order_no,
                    o.customer_display_name,
                    o.customer_discord_id,
                    o.category,
                    o.item,
                    o.quantity,
                    o.amount,
                    o.status AS order_status,
                    o.closed_at,
                    o.updated_at,
                    r.id AS report_id,
                    COALESCE(r.status, 'approved') AS report_status,
                    COALESCE(r.is_legacy, 1) AS is_legacy,
                    r.streamed,
                    r.recording_saved,
                    r.recording_holder,
                    r.note,
                    r.submitted_by_discord_id,
                    r.submitted_by_display_name,
                    r.submitted_at,
                    r.reviewed_by_discord_id,
                    r.reviewed_by_display_name,
                    r.reviewed_at,
                    r.review_note
                FROM web_orders o
                LEFT JOIN order_reports r ON r.order_id = o.id
                WHERE o.id = :order_id
                  AND LOWER(TRIM(COALESCE(o.status, ''))) = 'closed'
                LIMIT 1
            """),
            {"order_id": int(order_id)},
        ).mappings().first()
        if order is None:
            return None

        workers = conn.execute(
            text("""
                SELECT
                    a.id AS assignment_id,
                    a.worker_discord_id,
                    a.worker_display_name,
                    a.role_type,
                    a.has_named_bonus AS current_named_bonus,
                    rw.has_named_bonus AS reported_named_bonus
                FROM order_assignments a
                LEFT JOIN order_report_workers rw
                  ON rw.report_id = :report_id
                 AND rw.worker_discord_id = a.worker_discord_id
                WHERE a.order_id = :order_id
                  AND COALESCE(a.is_active, 0) = 1
                ORDER BY a.assigned_at ASC, a.id ASC
            """),
            {
                "order_id": int(order_id),
                "report_id": int(order.get("report_id") or 0),
            },
        ).mappings().all()

        audit_rows = []
        if order.get("report_id"):
            audit_rows = conn.execute(
                text("""
                    SELECT
                        action,
                        actor_display_name,
                        note,
                        created_at
                    FROM order_report_audit
                    WHERE report_id = :report_id
                    ORDER BY id DESC
                    LIMIT 20
                """),
                {"report_id": int(order["report_id"])},
            ).mappings().all()

    result = dict(order)
    result["workers"] = [dict(row) for row in workers]
    result["audit"] = [dict(row) for row in audit_rows]
    result["status_label"] = _status_label(result.get("report_status"))
    return result


def get_report_detail_for_worker(order_id: int, worker_discord_id: str) -> dict | None:
    detail = _load_report_detail(order_id)
    if detail is None:
        return None

    worker_id = str(worker_discord_id or "").strip()
    if not any(str(row.get("worker_discord_id")) == worker_id for row in detail["workers"]):
        return None
    return detail


def get_report_detail_for_support(order_id: int) -> dict | None:
    return _load_report_detail(order_id)


def count_pending_review_reports() -> int:
    ensure_order_reporting_tables()
    with engine.begin() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM order_reports WHERE status = 'pending'")
            ).scalar_one()
            or 0
        )


def get_report_statuses(order_ids: list[int]) -> dict[int, str]:
    ids = sorted({int(value) for value in order_ids if int(value) > 0})
    if not ids:
        return {}
    ensure_order_reporting_tables()
    placeholders = ",".join(f":id_{index}" for index, _ in enumerate(ids))
    params = {f"id_{index}": value for index, value in enumerate(ids)}
    with engine.begin() as conn:
        rows = conn.execute(
            text(f"""
                SELECT
                    o.id,
                    CASE
                        WHEN LOWER(TRIM(COALESCE(o.status, ''))) != 'closed' THEN NULL
                        ELSE COALESCE(r.status, 'approved')
                    END AS report_status
                FROM web_orders o
                LEFT JOIN order_reports r ON r.order_id = o.id
                WHERE o.id IN ({placeholders})
            """),
            params,
        ).mappings().all()
    return {
        int(row["id"]): str(row["report_status"])
        for row in rows
        if row.get("report_status")
    }


def _report_snapshot(conn, report_id: int) -> dict:
    report = conn.execute(
        select(order_reports).where(order_reports.c.id == int(report_id))
    ).mappings().first()
    workers = conn.execute(
        select(order_report_workers)
        .where(order_report_workers.c.report_id == int(report_id))
        .order_by(order_report_workers.c.id.asc())
    ).mappings().all()
    return {
        "report": dict(report) if report is not None else None,
        "workers": [dict(row) for row in workers],
    }


def _write_report_audit(
    conn,
    *,
    report_id: int,
    action: str,
    actor: Mapping[str, Any] | None,
    before: dict | None,
    after: dict | None,
    note: str | None = None,
) -> None:
    conn.execute(
        order_report_audit.insert().values(
            report_id=int(report_id),
            action=str(action),
            actor_discord_id=str((actor or {}).get("id") or "") or None,
            actor_display_name=_display_name(actor),
            before_json=_safe_json(before) if before is not None else None,
            after_json=_safe_json(after) if after is not None else None,
            note=_trimmed(note, REVIEW_NOTE_MAX_LENGTH),
            created_at=_now(),
        )
    )


def submit_order_report(
    *,
    order_id: int,
    user: Mapping[str, Any],
    streamed: bool,
    recording_saved: bool,
    recording_holder: str | None,
    note: str | None,
    named_bonus_by_worker: Mapping[str, bool],
) -> None:
    ensure_order_reporting_tables()
    worker_id = str(user.get("id") or "").strip()
    if not worker_id:
        raise ValueError("登入狀態已失效，請重新登入。")

    note_text = _trimmed(note, REPORT_NOTE_MAX_LENGTH)
    holder_text = _trimmed(recording_holder, 120) if recording_saved else None

    with engine.begin() as conn:
        order = conn.execute(
            text("""
                SELECT o.id, o.status, r.id AS report_id, r.status AS report_status, r.is_legacy
                FROM web_orders o
                JOIN order_reports r ON r.order_id = o.id
                WHERE o.id = :order_id
                LIMIT 1
            """),
            {"order_id": int(order_id)},
        ).mappings().first()
        if order is None or str(order.get("status") or "").lower() != "closed":
            raise ValueError("這張訂單尚未結單，不能填寫報單。")
        if int(order.get("is_legacy") or 0) == 1:
            raise ValueError("這是舊制訂單，系統已視為完成報單。")
        if str(order.get("report_status") or "") not in {
            REPORT_STATUS_MISSING,
            REPORT_STATUS_CHANGES_REQUESTED,
        }:
            raise ValueError("這張報單目前已送審或完成審核，不能再修改。")

        workers = conn.execute(
            text("""
                SELECT worker_discord_id, worker_display_name
                FROM order_assignments
                WHERE order_id = :order_id
                  AND COALESCE(is_active, 0) = 1
                ORDER BY assigned_at ASC, id ASC
            """),
            {"order_id": int(order_id)},
        ).mappings().all()
        worker_ids = {str(row["worker_discord_id"]) for row in workers}
        if worker_id not in worker_ids:
            raise ValueError("只有實際參與這張訂單的陪玩／打手可以填寫報單。")
        if not workers:
            raise ValueError("這張訂單沒有可報單的接單人員。")

        missing_named = sorted(worker_ids - {str(key) for key in named_bonus_by_worker})
        if missing_named:
            raise ValueError("請確認本單每位接單人員是否掛名。")

        report_id = int(order["report_id"])
        before = _report_snapshot(conn, report_id)
        conn.execute(
            order_reports.update()
            .where(order_reports.c.id == report_id)
            .values(
                status=REPORT_STATUS_PENDING,
                streamed=_to_bool_int(streamed),
                recording_saved=_to_bool_int(recording_saved),
                recording_holder=holder_text,
                note=note_text,
                submitted_by_discord_id=worker_id,
                submitted_by_display_name=_display_name(user),
                submitted_at=_now(),
                reviewed_by_discord_id=None,
                reviewed_by_display_name=None,
                reviewed_at=None,
                review_note=None,
                updated_at=_now(),
            )
        )
        conn.execute(
            order_report_workers.delete().where(
                order_report_workers.c.report_id == report_id
            )
        )
        for row in workers:
            current_worker_id = str(row["worker_discord_id"])
            conn.execute(
                order_report_workers.insert().values(
                    report_id=report_id,
                    worker_discord_id=current_worker_id,
                    worker_display_name=row.get("worker_display_name") or current_worker_id,
                    has_named_bonus=_to_bool_int(named_bonus_by_worker.get(current_worker_id)),
                )
            )

        conn.execute(
            order_report_reminders.update()
            .where(order_report_reminders.c.order_id == int(order_id))
            .values(status="cancelled", updated_at=_now())
        )
        after = _report_snapshot(conn, report_id)
        _write_report_audit(
            conn,
            report_id=report_id,
            action="submitted" if before.get("report", {}).get("status") == REPORT_STATUS_MISSING else "resubmitted",
            actor=user,
            before=before,
            after=after,
        )


def _preserve_paid_states_and_recalculate(db, order_id: int) -> None:
    old_worker = {
        str(row.worker_discord_id): (str(row.payout_status), row.paid_at)
        for row in db.scalars(
            select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
        ).all()
    }
    old_cs = {
        str(row.customer_service_discord_id): (str(row.payout_status), row.paid_at)
        for row in db.scalars(
            select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
        ).all()
    }

    recalculate_order_payouts(db, int(order_id))
    db.flush()

    for row in db.scalars(
        select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
    ).all():
        previous = old_worker.get(str(row.worker_discord_id))
        if previous and previous[0] == PayoutStatus.PAID.value:
            row.payout_status = PayoutStatus.PAID.value
            row.paid_at = previous[1]

    for row in db.scalars(
        select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
    ).all():
        previous = old_cs.get(str(row.customer_service_discord_id))
        if previous and previous[0] == PayoutStatus.PAID.value:
            row.payout_status = PayoutStatus.PAID.value
            row.paid_at = previous[1]


def review_order_report(
    *,
    order_id: int,
    admin_user: Mapping[str, Any],
    action: str,
    review_note: str | None = None,
    streamed: bool | None = None,
    recording_saved: bool | None = None,
    recording_holder: str | None = None,
    note: str | None = None,
    named_bonus_by_worker: Mapping[str, bool] | None = None,
) -> None:
    ensure_order_reporting_tables()
    action = str(action or "").strip()
    if action not in {REPORT_STATUS_APPROVED, REPORT_STATUS_CHANGES_REQUESTED}:
        raise ValueError("不支援的報單審核操作。")

    review_note_text = _trimmed(review_note, REVIEW_NOTE_MAX_LENGTH)
    if action == REPORT_STATUS_CHANGES_REQUESTED and not review_note_text:
        raise ValueError("退回修改時請填寫原因。")

    db = SessionLocal()
    try:
        order = db.get(WebOrder, int(order_id))
        if order is None or str(order.status or "").lower() != "closed":
            raise ValueError("找不到已結單的訂單。")

        conn = db.connection()
        report = conn.execute(
            select(order_reports).where(order_reports.c.order_id == int(order_id))
        ).mappings().first()
        if report is None:
            raise ValueError("找不到這張訂單的報單狀態。")
        if int(report.get("is_legacy") or 0) == 1:
            raise ValueError("舊制訂單已視為報單完成，不需要再次審核。")
        report_id = int(report["id"])
        before = _report_snapshot(conn, report_id)

        if action == REPORT_STATUS_CHANGES_REQUESTED:
            if str(report.get("status") or "") not in {REPORT_STATUS_PENDING, REPORT_STATUS_CHANGES_REQUESTED}:
                raise ValueError("這張報單尚未送審，不能退回修改。")
            conn.execute(
                order_reports.update()
                .where(order_reports.c.id == report_id)
                .values(
                    status=REPORT_STATUS_CHANGES_REQUESTED,
                    reviewed_by_discord_id=str(admin_user.get("id") or "") or None,
                    reviewed_by_display_name=_display_name(admin_user),
                    reviewed_at=_now(),
                    review_note=review_note_text,
                    updated_at=_now(),
                )
            )
            after = _report_snapshot(conn, report_id)
            _write_report_audit(
                conn,
                report_id=report_id,
                action="changes_requested",
                actor=admin_user,
                before=before,
                after=after,
                note=review_note_text,
            )
            from web.app.services.admin_service import write_admin_audit_log

            write_admin_audit_log(
                db,
                admin_user=dict(admin_user),
                action="order_report_changes_requested",
                target_type="web_order",
                target_id=str(order_id),
                before=before,
                after=after,
            )
            db.commit()
            return

        # Approval may also be used by CS to complete a missing report on behalf of
        # the workers. Therefore the editable report fields are validated here.
        if streamed is None or recording_saved is None:
            raise ValueError("確認通過前，請確認直播與錄影狀態。")

        assignments = list(
            db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == int(order_id))
                .where(OrderAssignment.is_active.is_(True))
                .order_by(OrderAssignment.assigned_at.asc(), OrderAssignment.id.asc())
            ).all()
        )
        if not assignments:
            raise ValueError("這張訂單沒有接單人員，請先確認訂單資料。")

        named_map = {str(key): bool(value) for key, value in (named_bonus_by_worker or {}).items()}
        missing_named = [
            str(row.worker_discord_id)
            for row in assignments
            if str(row.worker_discord_id) not in named_map
        ]
        if missing_named:
            raise ValueError("確認通過前，請確認本單每位接單人員是否掛名。")

        conn.execute(
            order_reports.update()
            .where(order_reports.c.id == report_id)
            .values(
                status=REPORT_STATUS_APPROVED,
                streamed=_to_bool_int(streamed),
                recording_saved=_to_bool_int(recording_saved),
                recording_holder=(
                    _trimmed(recording_holder, 120)
                    if recording_saved
                    else None
                ),
                note=_trimmed(note, REPORT_NOTE_MAX_LENGTH),
                reviewed_by_discord_id=str(admin_user.get("id") or "") or None,
                reviewed_by_display_name=_display_name(admin_user),
                reviewed_at=_now(),
                review_note=review_note_text,
                updated_at=_now(),
            )
        )
        conn.execute(
            order_report_workers.delete().where(
                order_report_workers.c.report_id == report_id
            )
        )

        for assignment in assignments:
            current_worker_id = str(assignment.worker_discord_id)
            enabled = bool(named_map[current_worker_id])
            assignment.has_named_bonus = enabled
            conn.execute(
                order_report_workers.insert().values(
                    report_id=report_id,
                    worker_discord_id=current_worker_id,
                    worker_display_name=(
                        assignment.worker_display_name
                        or current_worker_id
                    ),
                    has_named_bonus=int(enabled),
                )
            )

        db.flush()
        _preserve_paid_states_and_recalculate(db, int(order_id))
        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_UPDATED,
            order_id=int(order_id),
            payload={
                "reason": "order_report_approved",
                "reviewed_by_discord_id": str(admin_user.get("id") or ""),
                "named_bonus_worker_ids": [
                    worker_id
                    for worker_id, enabled in named_map.items()
                    if enabled
                ],
            },
        )
        after = _report_snapshot(conn, report_id)
        _write_report_audit(
            conn,
            report_id=report_id,
            action="approved",
            actor=admin_user,
            before=before,
            after=after,
            note=review_note_text,
        )

        from web.app.services.admin_service import write_admin_audit_log

        write_admin_audit_log(
            db,
            admin_user=dict(admin_user),
            action="order_report_approved",
            target_type="web_order",
            target_id=str(order_id),
            before=before,
            after=after,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_order_report_reminders(order_id: int) -> int:
    ensure_order_reporting_tables()
    with engine.begin() as conn:
        report_status = conn.execute(
            text("SELECT status FROM order_reports WHERE order_id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).scalar_one_or_none()
        if report_status != REPORT_STATUS_MISSING:
            return 0
        _queue_missing_reminders(conn, int(order_id))
        result = conn.execute(
            order_report_reminders.update()
            .where(order_report_reminders.c.order_id == int(order_id))
            .values(
                status="pending",
                attempts=0,
                last_error=None,
                sent_at=None,
                updated_at=_now(),
            )
        )
        return int(result.rowcount or 0)


def _claim_pending_reminders(limit: int, order_id: int | None = None) -> list[dict]:
    ensure_order_reporting_tables()
    claimed: list[dict] = []
    with engine.begin() as conn:
        params: dict[str, Any] = {
            "max_attempts": REMINDER_MAX_ATTEMPTS,
            "limit": max(1, min(int(limit), 50)),
        }
        order_filter = ""
        if order_id is not None:
            order_filter = " AND rr.order_id = :order_id"
            params["order_id"] = int(order_id)

        candidates = conn.execute(
            text(
                """
                SELECT
                    rr.id,
                    rr.order_id,
                    rr.worker_discord_id,
                    rr.attempts,
                    o.bot_order_no,
                    o.customer_display_name,
                    o.item,
                    o.closed_at
                FROM order_report_reminders rr
                JOIN order_reports r ON r.order_id = rr.order_id
                JOIN web_orders o ON o.id = rr.order_id
                WHERE rr.status IN ('pending', 'failed')
                  AND rr.attempts < :max_attempts
                  AND r.status = 'missing'
                """
                + order_filter
                + " ORDER BY rr.id ASC LIMIT :limit"
            ),
            params,
        ).mappings().all()

        for row in candidates:
            result = conn.execute(
                text("""
                    UPDATE order_report_reminders
                    SET status = 'processing',
                        attempts = attempts + 1,
                        updated_at = :now
                    WHERE id = :id
                      AND status IN ('pending', 'failed')
                """),
                {"id": int(row["id"]), "now": _now()},
            )
            if int(result.rowcount or 0) == 1:
                claimed.append(dict(row))
    return claimed


def _finish_reminder(reminder_id: int, *, success: bool, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            order_report_reminders.update()
            .where(order_report_reminders.c.id == int(reminder_id))
            .values(
                status="sent" if success else "failed",
                last_error=None if success else _trimmed(error, 800),
                sent_at=_now() if success else None,
                updated_at=_now(),
            )
        )


async def _send_discord_report_dm(client: httpx.AsyncClient, reminder: Mapping[str, Any]) -> None:
    token = str(config.DISCORD_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN 未設定")

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    recipient_id = str(reminder.get("worker_discord_id") or "").strip()
    dm_response = await client.post(
        "https://discord.com/api/v10/users/@me/channels",
        headers=headers,
        json={"recipient_id": recipient_id},
    )
    dm_response.raise_for_status()
    channel_id = str(dm_response.json().get("id") or "").strip()
    if not channel_id:
        raise RuntimeError("Discord 未回傳私訊頻道 ID")

    order_no = str(reminder.get("bot_order_no") or f"WEB-{reminder.get('order_id')}")
    customer = str(reminder.get("customer_display_name") or "未記錄")
    item = str(reminder.get("item") or "未記錄")
    closed_at = str(reminder.get("closed_at") or "").strip() or "剛剛"
    report_url = f"{_public_base_url()}/dispatch/reports/{int(reminder['order_id'])}"
    content = (
        "📋 **訂單已結單・請填寫報單**\n\n"
        f"訂單：{order_no}\n"
        f"老闆：{customer}\n"
        f"單別：{item}\n"
        f"結單時間：{closed_at}\n\n"
        "本單任一參與陪玩／打手填寫一次即可；隊友已填就不必重複。\n"
        "請點下方按鈕進入報單頁。"
    )
    message_response = await client.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers=headers,
        json={
            "content": content,
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 5,
                            "label": "填寫報單",
                            "url": report_url,
                            "emoji": {"name": "📝"},
                        }
                    ],
                }
            ],
            "allowed_mentions": {"parse": []},
        },
    )
    message_response.raise_for_status()


async def send_pending_order_report_reminders(
    *,
    limit: int = 20,
    order_id: int | None = None,
) -> dict[str, int]:
    reminders = _claim_pending_reminders(limit, order_id=order_id)
    result = {"claimed": len(reminders), "sent": 0, "failed": 0}
    if not reminders:
        return result

    async with httpx.AsyncClient(timeout=10.0) as client:
        for reminder in reminders:
            try:
                await _send_discord_report_dm(client, reminder)
            except Exception as exc:
                result["failed"] += 1
                _finish_reminder(
                    int(reminder["id"]),
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            else:
                result["sent"] += 1
                _finish_reminder(int(reminder["id"]), success=True)
    return result


async def order_report_reminder_loop() -> None:
    while True:
        try:
            await send_pending_order_report_reminders(limit=20)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                f"[order-report-reminder] {type(exc).__name__}: {exc}",
                flush=True,
            )
        await asyncio.sleep(REMINDER_LOOP_SECONDS)
