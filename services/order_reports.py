from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from sqlalchemy import inspect, select, text

from core.time_utils import get_taipei_now
from shared.db import SessionLocal, engine
from shared.models import CustomerServicePayout, OrderAssignment, WorkerPayout


REPORT_PENDING = "pending"
REPORT_SUBMITTED = "submitted"
REPORT_CHANGES_REQUESTED = "changes_requested"
REPORT_APPROVED = "approved"

REPORT_STATUS_LABELS = {
    REPORT_PENDING: "待填寫",
    REPORT_SUBMITTED: "待審核",
    REPORT_CHANGES_REQUESTED: "需修改",
    REPORT_APPROVED: "已完成",
}

REPORT_URL = "https://mowanentertainment.com/reports"
MAX_NOTIFICATION_ATTEMPTS = 3
REMINDER_COOLDOWN_MINUTES = 10

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _taipei_now_naive() -> datetime:
    return get_taipei_now().replace(tzinfo=None)


def _format_time(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    raw = str(value).strip()
    if not raw:
        return ""
    raw = raw.replace("T", " ")
    return raw[:16].replace("-", "/")


def _display_name(user: dict | None) -> str:
    user = user or {}
    return str(
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


def _ensure_base_report_tables(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS order_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            streamed INTEGER NOT NULL DEFAULT 0,
            recording_saved INTEGER NOT NULL DEFAULT 0,
            submitted_by_discord_id TEXT,
            submitted_by_display_name TEXT,
            submitted_at DATETIME,
            reviewed_by_discord_id TEXT,
            reviewed_by_display_name TEXT,
            reviewed_at DATETIME,
            review_note TEXT,
            last_reminded_at DATETIME,
            last_reminded_by_discord_id TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_order_reports_status_created
        ON order_reports(status, created_at)
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS order_report_workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            worker_discord_id TEXT NOT NULL,
            worker_display_name TEXT,
            has_named_bonus INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(order_id, worker_discord_id)
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_order_report_workers_worker_order
        ON order_report_workers(worker_discord_id, order_id)
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS order_report_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            worker_discord_id TEXT NOT NULL,
            notification_kind TEXT NOT NULL DEFAULT 'report_required',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at DATETIME,
            last_error TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at DATETIME,
            UNIQUE(order_id, worker_discord_id, notification_kind)
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_order_report_notifications_queue
        ON order_report_notifications(status, next_attempt_at, id)
    """))


def _ensure_sqlite_close_trigger(conn) -> bool:
    try:
        has_orders = inspect(conn).has_table("web_orders")
        has_assignments = inspect(conn).has_table("order_assignments")
    except Exception:
        return False

    if not (has_orders and has_assignments):
        return False

    # 不回填既有已結單資料：只有部署後「從非 closed 轉成 closed」的訂單
    # 才建立報單。這正好讓舊報單制度從新結單開始切換，不會追舊帳。
    conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS trg_order_reports_after_close
        AFTER UPDATE OF status ON web_orders
        WHEN LOWER(TRIM(COALESCE(NEW.status, ''))) = 'closed'
         AND LOWER(TRIM(COALESCE(OLD.status, ''))) <> 'closed'
         AND EXISTS (
             SELECT 1
             FROM order_assignments a
             WHERE a.order_id = NEW.id
               AND COALESCE(a.is_active, 0) = 1
         )
        BEGIN
            INSERT OR IGNORE INTO order_reports (
                order_id,
                status,
                created_at,
                updated_at
            ) VALUES (
                NEW.id,
                'pending',
                datetime('now', '+8 hours'),
                datetime('now', '+8 hours')
            );

            INSERT OR IGNORE INTO order_report_workers (
                report_id,
                order_id,
                worker_discord_id,
                worker_display_name,
                has_named_bonus,
                created_at,
                updated_at
            )
            SELECT
                r.id,
                NEW.id,
                a.worker_discord_id,
                a.worker_display_name,
                0,
                datetime('now', '+8 hours'),
                datetime('now', '+8 hours')
            FROM order_assignments a
            JOIN order_reports r
              ON r.order_id = NEW.id
            WHERE a.order_id = NEW.id
              AND COALESCE(a.is_active, 0) = 1;

            INSERT OR IGNORE INTO order_report_notifications (
                order_id,
                worker_discord_id,
                notification_kind,
                status,
                attempts,
                created_at
            )
            SELECT
                NEW.id,
                a.worker_discord_id,
                'report_required',
                'pending',
                0,
                datetime('now', '+8 hours')
            FROM order_assignments a
            WHERE a.order_id = NEW.id
              AND COALESCE(a.is_active, 0) = 1;
        END
    """))
    return True


def ensure_order_report_tables(bind=engine) -> bool:
    global _SCHEMA_READY

    if bind is engine and _SCHEMA_READY:
        return True

    with _SCHEMA_LOCK:
        if bind is engine and _SCHEMA_READY:
            return True

        with bind.begin() as conn:
            _ensure_base_report_tables(conn)
            trigger_ready = True
            if getattr(bind.dialect, "name", "") == "sqlite":
                trigger_ready = _ensure_sqlite_close_trigger(conn)

        if bind is engine and trigger_ready:
            _SCHEMA_READY = True

        return trigger_ready


def _fetch_report_workers(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT
                worker_discord_id,
                worker_display_name,
                has_named_bonus
            FROM order_report_workers
            WHERE order_id = :order_id
            ORDER BY id ASC
        """),
        {"order_id": int(order_id)},
    ).mappings().all()
    return [
        {
            "worker_discord_id": str(row["worker_discord_id"] or ""),
            "worker_display_name": str(
                row["worker_display_name"]
                or row["worker_discord_id"]
                or "未知人員"
            ),
            "has_named_bonus": bool(row["has_named_bonus"]),
        }
        for row in rows
    ]


def _decorate_report(db, row) -> dict:
    item = dict(row)
    item["order_id"] = int(item["order_id"])
    item["workers"] = _fetch_report_workers(db, int(item["order_id"]))
    item["status_label"] = REPORT_STATUS_LABELS.get(
        str(item.get("status") or ""),
        str(item.get("status") or "未知"),
    )
    item["streamed"] = bool(item.get("streamed"))
    item["recording_saved"] = bool(item.get("recording_saved"))
    item["closed_at_text"] = _format_time(item.get("closed_at"))
    item["submitted_at_text"] = _format_time(item.get("submitted_at"))
    item["reviewed_at_text"] = _format_time(item.get("reviewed_at"))
    item["last_reminded_at_text"] = _format_time(item.get("last_reminded_at"))
    item["can_submit"] = str(item.get("status") or "") in {
        REPORT_PENDING,
        REPORT_CHANGES_REQUESTED,
    }
    return item


def _base_report_select_sql() -> str:
    return """
        SELECT
            r.id AS report_id,
            r.order_id,
            r.status,
            r.streamed,
            r.recording_saved,
            r.submitted_by_discord_id,
            r.submitted_by_display_name,
            r.submitted_at,
            r.reviewed_by_discord_id,
            r.reviewed_by_display_name,
            r.reviewed_at,
            r.review_note,
            r.last_reminded_at,
            r.last_reminded_by_discord_id,
            r.created_at,
            r.updated_at,
            o.bot_order_no,
            o.customer_display_name,
            o.customer_discord_id,
            o.category,
            o.item,
            o.closed_at,
            o.amount,
            o.customer_pay_amount
        FROM order_reports r
        JOIN web_orders o
          ON o.id = r.order_id
    """


def list_reports_for_user(discord_user_id: str | int) -> list[dict]:
    ensure_order_report_tables()
    user_id = str(discord_user_id or "").strip()
    if not user_id:
        return []

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                _base_report_select_sql()
                + """
                JOIN order_report_workers mine
                  ON mine.order_id = r.order_id
                 AND mine.worker_discord_id = :worker_id
                ORDER BY COALESCE(o.closed_at, r.created_at) DESC, r.id DESC
                LIMIT 120
                """
            ),
            {"worker_id": user_id},
        ).mappings().all()
        return [_decorate_report(db, row) for row in rows]
    finally:
        db.close()


def list_reports_for_review(
    *,
    status_filter: str = "open",
    order_id: int | None = None,
) -> list[dict]:
    ensure_order_report_tables()
    filters: list[str] = []
    params: dict = {}

    normalized = str(status_filter or "open").strip().lower()
    if normalized == "open":
        filters.append("r.status IN ('pending', 'submitted', 'changes_requested')")
    elif normalized in REPORT_STATUS_LABELS:
        filters.append("r.status = :status")
        params["status"] = normalized
    elif normalized != "all":
        filters.append("r.status IN ('pending', 'submitted', 'changes_requested')")

    if order_id is not None:
        filters.append("r.order_id = :order_id")
        params["order_id"] = int(order_id)

    where_sql = (" WHERE " + " AND ".join(filters)) if filters else ""

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                _base_report_select_sql()
                + where_sql
                + " ORDER BY CASE r.status WHEN 'submitted' THEN 0 WHEN 'changes_requested' THEN 1 WHEN 'pending' THEN 2 ELSE 3 END, COALESCE(r.submitted_at, r.created_at) ASC"
            ),
            params,
        ).mappings().all()
        return [_decorate_report(db, row) for row in rows]
    finally:
        db.close()


def get_report_counts(reports: list[dict]) -> dict[str, int]:
    counts = {
        REPORT_PENDING: 0,
        REPORT_SUBMITTED: 0,
        REPORT_CHANGES_REQUESTED: 0,
        REPORT_APPROVED: 0,
    }
    for report in reports:
        status = str(report.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def submit_order_report(
    *,
    order_id: int,
    user: dict,
    streamed: bool,
    recording_saved: bool,
    named_worker_ids: list[str] | tuple[str, ...] | None,
) -> None:
    ensure_order_report_tables()
    actor_id = str(user.get("id") or "").strip()
    if not actor_id:
        raise ValueError("登入狀態已失效，請重新登入。")

    named_ids = {
        str(worker_id).strip()
        for worker_id in (named_worker_ids or [])
        if str(worker_id).strip()
    }

    db = SessionLocal()
    try:
        report = db.execute(
            text("""
                SELECT id, status
                FROM order_reports
                WHERE order_id = :order_id
                LIMIT 1
            """),
            {"order_id": int(order_id)},
        ).mappings().first()
        if report is None:
            raise ValueError("這張訂單不需要使用新版報單，或報單資料尚未建立。")

        status = str(report["status"] or "")
        if status not in {REPORT_PENDING, REPORT_CHANGES_REQUESTED}:
            raise ValueError("這張報單目前不能修改。")

        participant = db.execute(
            text("""
                SELECT 1
                FROM order_report_workers
                WHERE order_id = :order_id
                  AND worker_discord_id = :worker_id
                LIMIT 1
            """),
            {"order_id": int(order_id), "worker_id": actor_id},
        ).first()
        if participant is None:
            raise ValueError("你沒有接過這張單，不能填寫這份報單。")

        valid_worker_ids = {
            str(row[0])
            for row in db.execute(
                text("""
                    SELECT worker_discord_id
                    FROM order_report_workers
                    WHERE order_id = :order_id
                """),
                {"order_id": int(order_id)},
            ).all()
        }
        if not named_ids.issubset(valid_worker_ids):
            raise ValueError("掛名人員資料已變更，請重新整理後再送出。")

        now = _taipei_now_naive()
        db.execute(
            text("""
                UPDATE order_report_workers
                SET has_named_bonus = CASE
                        WHEN worker_discord_id IN (
                            SELECT value FROM json_each(:named_ids_json)
                        ) THEN 1 ELSE 0 END,
                    updated_at = :updated_at
                WHERE order_id = :order_id
            """),
            {
                "named_ids_json": json.dumps(sorted(named_ids), ensure_ascii=False),
                "updated_at": now,
                "order_id": int(order_id),
            },
        )
        db.execute(
            text("""
                UPDATE order_reports
                SET status = 'submitted',
                    streamed = :streamed,
                    recording_saved = :recording_saved,
                    submitted_by_discord_id = :actor_id,
                    submitted_by_display_name = :actor_name,
                    submitted_at = :submitted_at,
                    reviewed_by_discord_id = NULL,
                    reviewed_by_display_name = NULL,
                    reviewed_at = NULL,
                    review_note = NULL,
                    updated_at = :updated_at
                WHERE order_id = :order_id
            """),
            {
                "streamed": 1 if streamed else 0,
                "recording_saved": 1 if recording_saved else 0,
                "actor_id": actor_id,
                "actor_name": _display_name(user),
                "submitted_at": now,
                "updated_at": now,
                "order_id": int(order_id),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _snapshot_payout_statuses(db, order_id: int):
    worker_state = {
        str(row.worker_discord_id): (row.payout_status, row.paid_at)
        for row in db.scalars(
            select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
        ).all()
    }
    cs_state = {
        str(row.customer_service_discord_id): (row.payout_status, row.paid_at)
        for row in db.scalars(
            select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
        ).all()
    }
    return worker_state, cs_state


def _restore_payout_statuses(db, order_id: int, worker_state, cs_state) -> None:
    db.flush()
    for payout in db.scalars(
        select(WorkerPayout).where(WorkerPayout.order_id == int(order_id))
    ).all():
        previous = worker_state.get(str(payout.worker_discord_id))
        if previous is not None:
            payout.payout_status, payout.paid_at = previous

    for payout in db.scalars(
        select(CustomerServicePayout).where(CustomerServicePayout.order_id == int(order_id))
    ).all():
        previous = cs_state.get(str(payout.customer_service_discord_id))
        if previous is not None:
            payout.payout_status, payout.paid_at = previous


def review_order_report(
    *,
    order_id: int,
    support_user: dict,
    action: str,
    note: str | None = None,
    streamed: bool | None = None,
    recording_saved: bool | None = None,
    named_worker_ids: list[str] | tuple[str, ...] | None = None,
) -> str:
    from web.app.services.admin_service import write_admin_audit_log
    from web.app.services.order_service import recalculate_order_payouts

    ensure_order_report_tables()
    action = str(action or "").strip().lower()
    reviewer_id = str(support_user.get("id") or "").strip()
    if not reviewer_id:
        raise ValueError("登入狀態已失效，請重新登入。")

    db = SessionLocal()
    try:
        report = db.execute(
            text("""
                SELECT *
                FROM order_reports
                WHERE order_id = :order_id
                LIMIT 1
            """),
            {"order_id": int(order_id)},
        ).mappings().first()
        if report is None:
            raise ValueError("找不到這份報單。")

        before = dict(report)
        status = str(report["status"] or "")
        now = _taipei_now_naive()

        if action == "request_changes":
            clean_note = str(note or "").strip()
            if status != REPORT_SUBMITTED:
                raise ValueError("只有待審核的報單可以退回修改。")
            if not clean_note:
                raise ValueError("退回修改時請填寫原因。")

            db.execute(
                text("""
                    UPDATE order_reports
                    SET status = 'changes_requested',
                        reviewed_by_discord_id = :reviewer_id,
                        reviewed_by_display_name = :reviewer_name,
                        reviewed_at = :reviewed_at,
                        review_note = :review_note,
                        updated_at = :updated_at
                    WHERE order_id = :order_id
                """),
                {
                    "reviewer_id": reviewer_id,
                    "reviewer_name": _display_name(support_user),
                    "reviewed_at": now,
                    "review_note": clean_note[:1000],
                    "updated_at": now,
                    "order_id": int(order_id),
                },
            )
            write_admin_audit_log(
                db,
                admin_user=support_user,
                action="order_report_request_changes",
                target_type="order_report",
                target_id=str(order_id),
                before=before,
                after={"status": REPORT_CHANGES_REQUESTED, "review_note": clean_note[:1000]},
            )
            db.commit()
            return "已退回修改。"

        if action != "approve":
            raise ValueError("未知的報單審核操作。")
        if status != REPORT_SUBMITTED:
            raise ValueError("只有待審核的報單可以通過。")

        valid_worker_ids = {
            str(row[0])
            for row in db.execute(
                text("SELECT worker_discord_id FROM order_report_workers WHERE order_id = :order_id"),
                {"order_id": int(order_id)},
            ).all()
        }
        if named_worker_ids is None:
            named_ids = {
                str(row[0])
                for row in db.execute(
                    text("SELECT worker_discord_id FROM order_report_workers WHERE order_id = :order_id AND has_named_bonus = 1"),
                    {"order_id": int(order_id)},
                ).all()
            }
        else:
            named_ids = {
                str(worker_id).strip()
                for worker_id in named_worker_ids
                if str(worker_id).strip()
            }
        if not named_ids.issubset(valid_worker_ids):
            raise ValueError("掛名人員資料已變更，請重新整理後再審核。")

        final_streamed = bool(report["streamed"]) if streamed is None else bool(streamed)
        final_recording = bool(report["recording_saved"]) if recording_saved is None else bool(recording_saved)

        db.execute(
            text("""
                UPDATE order_report_workers
                SET has_named_bonus = CASE
                        WHEN worker_discord_id IN (
                            SELECT value FROM json_each(:named_ids_json)
                        ) THEN 1 ELSE 0 END,
                    updated_at = :updated_at
                WHERE order_id = :order_id
            """),
            {
                "named_ids_json": json.dumps(sorted(named_ids), ensure_ascii=False),
                "updated_at": now,
                "order_id": int(order_id),
            },
        )

        # 報單通過前掛名只存在報單草稿；通過後才真正套到薪資來源。
        db.execute(
            text("""
                UPDATE order_assignments
                SET has_named_bonus = CASE
                        WHEN worker_discord_id IN (
                            SELECT value FROM json_each(:named_ids_json)
                        ) THEN 1 ELSE 0 END
                WHERE order_id = :order_id
                  AND is_active = 1
            """),
            {
                "named_ids_json": json.dumps(sorted(named_ids), ensure_ascii=False),
                "order_id": int(order_id),
            },
        )

        worker_state, cs_state = _snapshot_payout_statuses(db, int(order_id))
        recalculate_order_payouts(db, int(order_id))
        _restore_payout_statuses(db, int(order_id), worker_state, cs_state)

        clean_note = str(note or "").strip()[:1000] or None
        db.execute(
            text("""
                UPDATE order_reports
                SET status = 'approved',
                    streamed = :streamed,
                    recording_saved = :recording_saved,
                    reviewed_by_discord_id = :reviewer_id,
                    reviewed_by_display_name = :reviewer_name,
                    reviewed_at = :reviewed_at,
                    review_note = :review_note,
                    updated_at = :updated_at
                WHERE order_id = :order_id
            """),
            {
                "streamed": 1 if final_streamed else 0,
                "recording_saved": 1 if final_recording else 0,
                "reviewer_id": reviewer_id,
                "reviewer_name": _display_name(support_user),
                "reviewed_at": now,
                "review_note": clean_note,
                "updated_at": now,
                "order_id": int(order_id),
            },
        )

        write_admin_audit_log(
            db,
            admin_user=support_user,
            action="order_report_approve",
            target_type="order_report",
            target_id=str(order_id),
            before=before,
            after={
                "status": REPORT_APPROVED,
                "streamed": final_streamed,
                "recording_saved": final_recording,
                "named_worker_ids": sorted(named_ids),
                "review_note": clean_note,
            },
        )
        db.commit()
        return "報單已通過，掛名與薪資已同步。"
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_report_status_map(order_ids: list[int]) -> dict[str, dict]:
    ensure_order_report_tables()
    result: dict[str, dict] = {}
    clean_ids = []
    for value in order_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in clean_ids:
            clean_ids.append(parsed)

    db = SessionLocal()
    try:
        for order_id in clean_ids[:100]:
            row = db.execute(
                text("""
                    SELECT
                        o.status AS order_status,
                        r.status AS report_status,
                        r.submitted_by_display_name,
                        r.submitted_at,
                        r.review_note,
                        (
                            SELECT COUNT(*)
                            FROM order_assignments a
                            WHERE a.order_id = o.id
                              AND a.is_active = 1
                        ) AS active_assignment_count,
                        (
                            SELECT n.status
                            FROM order_report_notifications n
                            WHERE n.order_id = o.id
                              AND n.notification_kind = 'report_required'
                            ORDER BY n.id DESC
                            LIMIT 1
                        ) AS notification_status
                    FROM web_orders o
                    LEFT JOIN order_reports r
                      ON r.order_id = o.id
                    WHERE o.id = :order_id
                    LIMIT 1
                """),
                {"order_id": int(order_id)},
            ).mappings().first()
            if row is None:
                continue

            order_status = str(row["order_status"] or "")
            report_status = str(row["report_status"] or "")
            assignment_count = int(row["active_assignment_count"] or 0)
            notification_status = str(row["notification_status"] or "")

            if report_status:
                label = REPORT_STATUS_LABELS.get(report_status, report_status)
                detail = ""
                if report_status == REPORT_PENDING:
                    if notification_status == "sent":
                        detail = "已私訊"
                    elif notification_status == "failed":
                        detail = "私訊失敗"
                    elif notification_status in {"pending", "processing"}:
                        detail = "私訊排程中"
                elif report_status == REPORT_SUBMITTED and row["submitted_by_display_name"]:
                    detail = f"{row['submitted_by_display_name']} 已送出"
                elif report_status == REPORT_CHANGES_REQUESTED:
                    detail = "客服退回"

                result[str(order_id)] = {
                    "required": True,
                    "status": report_status,
                    "label": label,
                    "detail": detail,
                    "submitted_at": _format_time(row["submitted_at"]),
                    "review_note": str(row["review_note"] or ""),
                }
                continue

            if order_status == "closed" and assignment_count > 0:
                result[str(order_id)] = {
                    "required": False,
                    "status": "legacy_exempt",
                    "label": "舊單免報",
                    "detail": "新版上線前結單",
                }
            elif order_status == "closed":
                result[str(order_id)] = {
                    "required": False,
                    "status": "not_required",
                    "label": "免報",
                    "detail": "無接單人員",
                }
            else:
                result[str(order_id)] = {
                    "required": False,
                    "status": "not_applicable",
                    "label": "—",
                    "detail": "",
                }
        return result
    finally:
        db.close()


def _get_notification_payload(order_id: int) -> dict | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                _base_report_select_sql()
                + " WHERE r.order_id = :order_id LIMIT 1"
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        if row is None:
            return None
        return _decorate_report(db, row)
    finally:
        db.close()


def _dm_content(report: dict, *, reminder: bool = False) -> str:
    order_no = report.get("bot_order_no") or f"WEB-{report.get('order_id')}"
    customer = report.get("customer_display_name") or "未記錄"
    service = f"{report.get('category') or '未記錄'}｜{report.get('item') or '未記錄'}"
    prefix = "📌 報單提醒" if reminder else "📋 訂單已結單，請填寫報單"
    extra = ""
    if str(report.get("status") or "") == REPORT_CHANGES_REQUESTED:
        note = str(report.get("review_note") or "").strip()
        extra = f"\n客服退回原因：{note or '請依客服指示修改'}"

    return (
        f"{prefix}\n\n"
        f"訂單：{order_no}\n"
        f"老闆：{customer}\n"
        f"服務：{service}\n"
        f"結單：{report.get('closed_at_text') or '剛剛'}"
        f"{extra}\n\n"
        "請確認掛名、是否開直播、是否保留錄影後送出客服審核：\n"
        f"{REPORT_URL}?order={int(report.get('order_id') or 0)}"
    )


def _claim_next_notification() -> dict | None:
    ensure_order_report_tables()
    now = _taipei_now_naive()
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT id, order_id, worker_discord_id, attempts
                FROM order_report_notifications
                WHERE status = 'pending'
                  AND attempts < :max_attempts
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                ORDER BY id ASC
                LIMIT 1
            """),
            {"max_attempts": MAX_NOTIFICATION_ATTEMPTS, "now": now},
        ).mappings().first()
        if row is None:
            return None
        updated = conn.execute(
            text("""
                UPDATE order_report_notifications
                SET status = 'processing'
                WHERE id = :id
                  AND status = 'pending'
            """),
            {"id": int(row["id"])},
        )
        if int(updated.rowcount or 0) != 1:
            return None
        return dict(row)


def process_pending_report_notifications(limit: int = 10) -> dict[str, int]:
    from web.app.services.discord_service import send_direct_message

    ensure_order_report_tables()
    sent = 0
    failed = 0

    for _ in range(max(1, int(limit or 1))):
        notification = _claim_next_notification()
        if notification is None:
            break

        notification_id = int(notification["id"])
        attempts = int(notification.get("attempts") or 0) + 1
        try:
            report = _get_notification_payload(int(notification["order_id"]))
            if report is None:
                raise RuntimeError("report_not_found")
            send_direct_message(
                str(notification["worker_discord_id"]),
                content=_dm_content(report),
            )
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE order_report_notifications
                        SET status = 'sent',
                            attempts = :attempts,
                            sent_at = :sent_at,
                            last_error = NULL,
                            next_attempt_at = NULL
                        WHERE id = :id
                    """),
                    {
                        "attempts": attempts,
                        "sent_at": _taipei_now_naive(),
                        "id": notification_id,
                    },
                )
            sent += 1
        except Exception as exc:
            terminal = attempts >= MAX_NOTIFICATION_ATTEMPTS
            next_attempt = None if terminal else _taipei_now_naive() + timedelta(minutes=15)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE order_report_notifications
                        SET status = :status,
                            attempts = :attempts,
                            next_attempt_at = :next_attempt_at,
                            last_error = :last_error
                        WHERE id = :id
                    """),
                    {
                        "status": "failed" if terminal else "pending",
                        "attempts": attempts,
                        "next_attempt_at": next_attempt,
                        "last_error": f"{type(exc).__name__}: {exc}"[:500],
                        "id": notification_id,
                    },
                )
            failed += 1

    return {"sent": sent, "failed": failed}


def send_manual_report_reminder(order_id: int, support_user: dict) -> dict[str, int]:
    from web.app.services.discord_service import send_direct_message

    ensure_order_report_tables()
    report = _get_notification_payload(int(order_id))
    if report is None:
        raise ValueError("找不到這份報單。")
    if str(report.get("status") or "") not in {
        REPORT_PENDING,
        REPORT_CHANGES_REQUESTED,
    }:
        raise ValueError("這份報單目前不需要再次提醒。")

    last_reminded = report.get("last_reminded_at")
    if isinstance(last_reminded, str):
        try:
            last_reminded = datetime.fromisoformat(last_reminded)
        except ValueError:
            last_reminded = None
    if isinstance(last_reminded, datetime):
        elapsed = _taipei_now_naive() - last_reminded.replace(tzinfo=None)
        if elapsed < timedelta(minutes=REMINDER_COOLDOWN_MINUTES):
            remaining = REMINDER_COOLDOWN_MINUTES - int(elapsed.total_seconds() // 60)
            raise ValueError(f"剛提醒過，約 {max(1, remaining)} 分鐘後才能再次提醒。")

    sent = 0
    failed = 0
    content = _dm_content(report, reminder=True)
    for worker in report.get("workers") or []:
        try:
            send_direct_message(worker["worker_discord_id"], content=content)
            sent += 1
        except Exception:
            failed += 1

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE order_reports
                SET last_reminded_at = :last_reminded_at,
                    last_reminded_by_discord_id = :actor_id,
                    updated_at = :updated_at
                WHERE order_id = :order_id
            """),
            {
                "last_reminded_at": _taipei_now_naive(),
                "actor_id": str(support_user.get("id") or ""),
                "updated_at": _taipei_now_naive(),
                "order_id": int(order_id),
            },
        )

    return {"sent": sent, "failed": failed}
