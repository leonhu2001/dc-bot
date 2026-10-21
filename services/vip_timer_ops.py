from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text


END_REQUEST_TTL_SECONDS = 180
VIP_TIMER_MINIMUM_SECONDS = 15 * 60
_SNAPSHOT_INSTALLED = False


def _timer():
    from services import vip_timer

    return vip_timer


def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    columns = {
        str(row[1])
        for row in db.execute(text(f"PRAGMA table_info({table})")).fetchall()
    }
    if column not in columns:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def ensure_vip_timer_ops_tables(db=None) -> None:
    timer = _timer()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        timer.ensure_vip_timer_tables(db)
        _ensure_column(db, "vip_timer_sessions", "vip_name_snapshot", "TEXT")
        _ensure_column(db, "vip_timer_sessions", "vip_discount_pay_rate_snapshot", "INTEGER")
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_end_requests (
                order_id INTEGER PRIMARY KEY,
                requester_discord_id TEXT NOT NULL,
                requester_side TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                segment_id INTEGER,
                action TEXT NOT NULL,
                before_json TEXT NOT NULL DEFAULT '{}',
                after_json TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL,
                actor_discord_id TEXT,
                created_at TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_disputes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                reason TEXT NOT NULL,
                resolution TEXT,
                created_by_discord_id TEXT,
                resolved_by_discord_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                alert_key TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                sent_at TEXT NOT NULL,
                UNIQUE(order_id, alert_key)
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_vip_timer_corrections_order ON vip_timer_corrections(order_id, id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_vip_timer_disputes_order ON vip_timer_disputes(order_id, status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_vip_timer_alerts_order ON vip_timer_alerts(order_id, sent_at)"))
        if owns:
            db.commit()
    finally:
        if owns:
            db.close()


def _current_vip_level_and_rate(customer_id: str) -> tuple[str, int]:
    from core.vip_levels import get_vip_discount_pay_rate
    from services.rewards import get_customer_reward_data, get_effective_member_level

    try:
        reward_data = get_customer_reward_data(int(str(customer_id)))
        level = get_effective_member_level(reward_data) or {}
    except Exception as exc:
        raise ValueError("暫時無法確認 VIP 等級，請稍後再試。") from exc
    vip_name = str(level.get("name") or "普通魔丸")
    pay_rate = max(0, min(100, int(get_vip_discount_pay_rate(vip_name))))
    return vip_name, pay_rate


def snapshot_vip_for_order(db, order_id: int, customer_id: str) -> tuple[str, int]:
    ensure_vip_timer_ops_tables(db)
    row = db.execute(text("""
        SELECT vip_name_snapshot, vip_discount_pay_rate_snapshot
        FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()
    if row is None:
        raise ValueError("找不到 VIP 自由計時單。")
    name = str(row.get("vip_name_snapshot") or "").strip()
    rate = row.get("vip_discount_pay_rate_snapshot")
    if name and rate is not None:
        return name, max(0, min(100, int(rate)))

    name, pay_rate = _current_vip_level_and_rate(str(customer_id))
    db.execute(text("""
        UPDATE vip_timer_sessions
        SET vip_name_snapshot=:name,
            vip_discount_pay_rate_snapshot=:rate,
            updated_at=:now
        WHERE order_id=:order_id
    """), {
        "name": name,
        "rate": int(pay_rate),
        "now": _timer().utc_iso(),
        "order_id": int(order_id),
    })
    _timer()._event(db, int(order_id), "vip_snapshot_locked", customer_id, {
        "vip_name": name,
        "vip_discount_pay_rate": int(pay_rate),
    })
    return name, pay_rate


def get_vip_snapshot(order_id: int, db=None) -> tuple[str, int]:
    timer = _timer()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        row = db.execute(text("""
            SELECT customer_discord_id, vip_name_snapshot, vip_discount_pay_rate_snapshot
            FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()
        if row is None:
            raise ValueError("找不到 VIP 自由計時單。")
        name = str(row.get("vip_name_snapshot") or "").strip()
        rate = row.get("vip_discount_pay_rate_snapshot")
        if not name or rate is None:
            name, rate = snapshot_vip_for_order(
                db, int(order_id), str(row.get("customer_discord_id") or "")
            )
            if owns:
                db.commit()
        return name, max(0, min(100, int(rate)))
    finally:
        if owns:
            db.close()


def install_vip_timer_snapshot_guard() -> None:
    global _SNAPSHOT_INSTALLED
    if _SNAPSHOT_INSTALLED:
        return
    timer = _timer()
    ensure_vip_timer_ops_tables()
    original_create = timer.create_vip_timer_session

    def create_with_vip_snapshot(db, *, order_id: int, customer_id: str, initial_rule_key: str):
        result = original_create(
            db,
            order_id=int(order_id),
            customer_id=str(customer_id),
            initial_rule_key=str(initial_rule_key),
        )
        snapshot_vip_for_order(db, int(order_id), str(customer_id))
        return result

    timer.create_vip_timer_session = create_with_vip_snapshot

    from services import vip_timer_billing_guard as billing

    def snapshot_level_and_rate(order_id: int) -> tuple[str, int]:
        return get_vip_snapshot(int(order_id))

    billing._vip_level_and_rate = snapshot_level_and_rate
    _SNAPSHOT_INSTALLED = True


def _actor_side(session: dict, actor_id: Any, staff_ids: list[str] | None) -> str:
    actor = str(actor_id or "").strip()
    if actor == str(session.get("customer_discord_id") or "").strip():
        return "customer"
    staff = {str(value).strip() for value in (staff_ids or []) if str(value).strip()}
    if actor and actor in staff:
        return "staff"
    return "support"


def _read_end_request(db, order_id: int) -> dict | None:
    timer = _timer()
    row = db.execute(text("""
        SELECT order_id, requester_discord_id, requester_side, requested_at, updated_at
        FROM vip_timer_end_requests WHERE order_id=:order_id LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    requested = timer.parse_dt(result.get("requested_at"))
    if requested is not None and timer.utc_now() - requested >= timedelta(seconds=END_REQUEST_TTL_SECONDS):
        db.execute(text("DELETE FROM vip_timer_end_requests WHERE order_id=:order_id"), {"order_id": int(order_id)})
        timer._event(db, int(order_id), "end_request_expired", result.get("requester_discord_id"), {
            "requester_side": result.get("requester_side")
        })
        return None
    return result


def get_end_request(order_id: int) -> dict | None:
    timer = _timer()
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        result = _read_end_request(db, int(order_id))
        db.commit()
        return result
    finally:
        db.close()


def clear_end_request(order_id: int, *, actor_id: Any = None, reason: str = "cleared") -> None:
    timer = _timer()
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        existing = _read_end_request(db, int(order_id))
        if existing is not None:
            db.execute(text("DELETE FROM vip_timer_end_requests WHERE order_id=:order_id"), {"order_id": int(order_id)})
            timer._event(db, int(order_id), "end_request_cleared", actor_id, {
                "reason": str(reason or "cleared"),
                "requester_side": existing.get("requester_side"),
            })
        db.commit()
    finally:
        db.close()


def request_or_confirm_end(order_id: int, actor_id: Any, staff_ids: list[str] | None = None) -> dict:
    timer = _timer()
    session = timer.get_session(int(order_id))
    if not session or str(session.get("status") or "") not in {"running", "paused"}:
        clear_end_request(int(order_id), actor_id=actor_id, reason="not_active")
        raise ValueError("目前不是可結束的計時狀態。")
    side = _actor_side(session, actor_id, staff_ids)
    if side == "support":
        clear_end_request(int(order_id), actor_id=actor_id, reason="support_override")
        return {"state": "confirmed", "confirmed": True, "forced": True}

    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        existing = _read_end_request(db, int(order_id))
        now = timer.utc_iso()
        if existing is None:
            db.execute(text("""
                INSERT INTO vip_timer_end_requests(
                    order_id, requester_discord_id, requester_side, requested_at, updated_at
                ) VALUES (:order_id,:actor,:side,:now,:now)
                ON CONFLICT(order_id) DO UPDATE SET
                    requester_discord_id=excluded.requester_discord_id,
                    requester_side=excluded.requester_side,
                    requested_at=excluded.requested_at,
                    updated_at=excluded.updated_at
            """), {"order_id": int(order_id), "actor": str(actor_id or ""), "side": side, "now": now})
            timer._event(db, int(order_id), "end_requested", actor_id, {"requester_side": side})
            db.commit()
            return {
                "state": "pending",
                "confirmed": False,
                "requester_side": side,
                "requester_discord_id": str(actor_id or ""),
                "waiting_for": "staff" if side == "customer" else "customer",
            }
        requester_side = str(existing.get("requester_side") or "")
        if requester_side == side:
            db.commit()
            return {
                "state": "pending",
                "confirmed": False,
                "already_requested": True,
                "requester_side": requester_side,
                "requester_discord_id": str(existing.get("requester_discord_id") or ""),
                "waiting_for": "staff" if requester_side == "customer" else "customer",
            }
        db.execute(text("DELETE FROM vip_timer_end_requests WHERE order_id=:order_id"), {"order_id": int(order_id)})
        timer._event(db, int(order_id), "end_confirmed", actor_id, {
            "requester_side": requester_side,
            "confirmer_side": side,
            "requester_discord_id": str(existing.get("requester_discord_id") or ""),
        })
        db.commit()
        return {"state": "confirmed", "confirmed": True, "forced": False}
    finally:
        db.close()


def _discount_amount(amount: int, pay_rate: int) -> int:
    value = Decimal(max(0, int(amount))) * Decimal(max(0, min(100, int(pay_rate)))) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _segment_effective_seconds(segment: dict, status: str) -> int:
    timer = _timer()
    seconds = max(0, int(segment.get("billable_seconds") or 0))
    if status == "running" and not segment.get("ended_at"):
        active = timer.parse_dt(segment.get("active_started_at"))
        if active is not None:
            seconds += max(0, int((timer.utc_now() - active).total_seconds()))
    return seconds


def _amount_from_segments(segments: list[dict], status: str) -> tuple[int, int]:
    seconds_total = 0
    amount = Decimal(0)
    for segment in segments:
        seconds = _segment_effective_seconds(segment, status)
        seconds_total += seconds
        amount += Decimal(max(0, int(segment.get("hourly_rate") or 0))) * Decimal(seconds) / Decimal(3600)
    if 0 < seconds_total < VIP_TIMER_MINIMUM_SECONDS:
        amount *= Decimal(VIP_TIMER_MINIMUM_SECONDS) / Decimal(seconds_total)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), seconds_total


def get_timer_detail(order_id: int) -> dict | None:
    timer = _timer()
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        session = db.execute(text("SELECT * FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1"), {"order_id": int(order_id)}).mappings().first()
        if session is None:
            return None
        session = dict(session)
        segments = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_segments WHERE order_id=:order_id ORDER BY seq"), {"order_id": int(order_id)}).mappings().all()]
        events = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_events WHERE order_id=:order_id ORDER BY id DESC LIMIT 100"), {"order_id": int(order_id)}).mappings().all()]
        corrections = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_corrections WHERE order_id=:order_id ORDER BY id DESC"), {"order_id": int(order_id)}).mappings().all()]
        disputes = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_disputes WHERE order_id=:order_id ORDER BY id DESC"), {"order_id": int(order_id)}).mappings().all()]
        alerts = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_alerts WHERE order_id=:order_id ORDER BY id DESC"), {"order_id": int(order_id)}).mappings().all()]
        order = db.execute(text("""
            SELECT id, bot_order_no, customer_discord_id, customer_display_name, category, item,
                   status, amount, original_amount, payout_base_amount, customer_pay_amount,
                   payment_method, ticket_channel_id, created_at, updated_at, closed_at
            FROM web_orders WHERE id=:order_id LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()
        claims = [dict(row) for row in db.execute(text("""
            SELECT staff_discord_id, staff_display_name, is_active, claimed_at, unclaimed_at
            FROM order_acceptance_claims WHERE order_id=:order_id ORDER BY id
        """), {"order_id": int(order_id)}).mappings().all()]
        end_request = _read_end_request(db, int(order_id))
        status = str(session.get("status") or "")
        gross_preview, live_seconds = _amount_from_segments(segments, status)
        vip_name, pay_rate = get_vip_snapshot(int(order_id), db=db)
        customer_preview = _discount_amount(gross_preview, pay_rate)
        ended_at = timer.parse_dt(session.get("ended_at"))
        pending_age_seconds = 0
        if status == "pending_payment" and ended_at is not None:
            pending_age_seconds = max(0, int((timer.utc_now() - ended_at).total_seconds()))
        db.commit()
        return {
            "session": session,
            "segments": segments,
            "events": events,
            "corrections": corrections,
            "disputes": disputes,
            "alerts": alerts,
            "order": dict(order) if order is not None else {},
            "claims": claims,
            "end_request": end_request,
            "vip_name_snapshot": vip_name,
            "vip_discount_pay_rate_snapshot": pay_rate,
            "gross_preview": gross_preview,
            "customer_preview": customer_preview,
            "live_seconds": live_seconds,
            "pending_age_seconds": pending_age_seconds,
        }
    finally:
        db.close()


def recalculate_pending_settlement(order_id: int, db=None, *, actor_id: Any = None, reason: str = "客服修正") -> dict:
    timer = _timer()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        session = db.execute(text("SELECT status FROM vip_timer_sessions WHERE order_id=:order_id"), {"order_id": int(order_id)}).mappings().first()
        if session is None or str(session.get("status") or "") != "pending_payment":
            raise ValueError("只有待付款的自由計時單可以重新結算。")
        segments = [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_segments WHERE order_id=:order_id ORDER BY seq"), {"order_id": int(order_id)}).mappings().all()]
        gross, total_seconds = _amount_from_segments(segments, "pending_payment")
        vip_name, pay_rate = get_vip_snapshot(int(order_id), db=db)
        customer_pay = _discount_amount(gross, pay_rate)
        row = db.execute(text("SELECT price_snapshot_json FROM web_orders WHERE id=:order_id"), {"order_id": int(order_id)}).mappings().first()
        try:
            snapshot = json.loads(str((row or {}).get("price_snapshot_json") or "{}"))
        except Exception:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        snapshot.update({
            "vip_timer": True,
            "original_amount": gross,
            "final_amount": customer_pay,
            "customer_pay_amount": customer_pay,
            "payout_base_amount": customer_pay,
            "vip_name": vip_name,
            "vip_discount_pay_rate": pay_rate,
            "vip_discount_amount": max(0, gross - customer_pay),
            "vip_snapshot_locked": True,
            "timer_total_seconds": total_seconds,
        })
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        db.execute(text("UPDATE vip_timer_sessions SET final_amount=:amount, updated_at=:now WHERE order_id=:order_id"), {
            "amount": customer_pay, "now": timer.utc_iso(), "order_id": int(order_id)
        })
        db.execute(text("""
            UPDATE web_orders SET amount=:pay, original_amount=:gross,
                payout_base_amount=:pay, customer_pay_amount=:pay,
                price_snapshot_json=:snapshot, updated_at=CURRENT_TIMESTAMP
            WHERE id=:order_id
        """), {"pay": customer_pay, "gross": gross, "snapshot": snapshot_text, "order_id": int(order_id)})
        db.execute(text("UPDATE order_acceptance_meta SET price_snapshot_json=:snapshot, updated_at=CURRENT_TIMESTAMP WHERE order_id=:order_id"), {
            "snapshot": snapshot_text, "order_id": int(order_id)
        })
        timer._event(db, int(order_id), "admin_recalculated", actor_id, {
            "reason": str(reason or "客服修正"), "gross": gross, "customer_pay": customer_pay,
            "vip_name": vip_name, "pay_rate": pay_rate, "seconds": total_seconds,
        })
        if owns:
            db.commit()
        return {"gross": gross, "customer_pay": customer_pay, "seconds": total_seconds, "vip_name": vip_name, "pay_rate": pay_rate}
    finally:
        if owns:
            db.close()


def correct_segment(
    order_id: int,
    segment_id: int,
    *,
    actor_id: Any,
    reason: str,
    billable_seconds: int,
    hourly_rate: int,
    staff_ids: list[str] | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict:
    timer = _timer()
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("客服修正必須填寫原因。")
    if int(billable_seconds) < 0 or int(hourly_rate) <= 0:
        raise ValueError("計費秒數不能小於 0，時薪必須大於 0。")
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        session = db.execute(text("SELECT status FROM vip_timer_sessions WHERE order_id=:order_id"), {"order_id": int(order_id)}).mappings().first()
        status = str((session or {}).get("status") or "")
        if status not in {"paused", "pending_payment"}:
            raise ValueError("修正計時前請先暫停；已付款／已取消訂單不可直接改計時紀錄。")
        row = db.execute(text("SELECT * FROM vip_timer_segments WHERE id=:segment_id AND order_id=:order_id"), {
            "segment_id": int(segment_id), "order_id": int(order_id)
        }).mappings().first()
        if row is None:
            raise ValueError("找不到指定計時區段。")
        before = dict(row)
        new_started = str(started_at or before.get("started_at") or "").strip()
        new_ended = str(ended_at if ended_at is not None else (before.get("ended_at") or "")).strip() or None
        if timer.parse_dt(new_started) is None:
            raise ValueError("開始時間格式無效。")
        if new_ended is not None and timer.parse_dt(new_ended) is None:
            raise ValueError("結束時間格式無效。")
        if new_ended is not None and timer.parse_dt(new_ended) < timer.parse_dt(new_started):
            raise ValueError("結束時間不能早於開始時間。")
        staff = []
        for value in (staff_ids if staff_ids is not None else json.loads(str(before.get("staff_ids_json") or "[]"))):
            worker_id = str(value or "").strip()
            if worker_id and worker_id not in staff:
                staff.append(worker_id)
        db.execute(text("""
            UPDATE vip_timer_segments
            SET billable_seconds=:seconds, hourly_rate=:rate, staff_ids_json=:staff,
                started_at=:started_at, ended_at=:ended_at, updated_at=:now
            WHERE id=:segment_id AND order_id=:order_id
        """), {
            "seconds": int(billable_seconds), "rate": int(hourly_rate),
            "staff": json.dumps(staff, ensure_ascii=False), "started_at": new_started,
            "ended_at": new_ended, "now": timer.utc_iso(), "segment_id": int(segment_id),
            "order_id": int(order_id),
        })
        after = dict(before)
        after.update({"billable_seconds": int(billable_seconds), "hourly_rate": int(hourly_rate), "staff_ids_json": json.dumps(staff, ensure_ascii=False), "started_at": new_started, "ended_at": new_ended})
        db.execute(text("""
            INSERT INTO vip_timer_corrections(order_id,segment_id,action,before_json,after_json,reason,actor_discord_id,created_at)
            VALUES (:order_id,:segment_id,'segment_corrected',:before,:after,:reason,:actor,:now)
        """), {
            "order_id": int(order_id), "segment_id": int(segment_id),
            "before": json.dumps(before, ensure_ascii=False, default=str, sort_keys=True),
            "after": json.dumps(after, ensure_ascii=False, default=str, sort_keys=True),
            "reason": reason, "actor": str(actor_id or ""), "now": timer.utc_iso(),
        })
        timer._event(db, int(order_id), "segment_corrected", actor_id, {"segment_id": int(segment_id), "reason": reason})
        result = None
        if status == "pending_payment":
            result = recalculate_pending_settlement(int(order_id), db=db, actor_id=actor_id, reason=reason)
        db.commit()
        return result or {"updated": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def open_dispute(order_id: int, *, actor_id: Any, reason: str) -> int:
    timer = _timer()
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("請填寫爭議內容。")
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        if db.execute(text("SELECT 1 FROM vip_timer_sessions WHERE order_id=:order_id"), {"order_id": int(order_id)}).first() is None:
            raise ValueError("找不到 VIP 自由計時單。")
        now = timer.utc_iso()
        result = db.execute(text("""
            INSERT INTO vip_timer_disputes(order_id,status,reason,created_by_discord_id,created_at,updated_at)
            VALUES (:order_id,'open',:reason,:actor,:now,:now)
        """), {"order_id": int(order_id), "reason": reason, "actor": str(actor_id or ""), "now": now})
        dispute_id = int(result.lastrowid or 0)
        timer._event(db, int(order_id), "dispute_opened", actor_id, {"dispute_id": dispute_id, "reason": reason})
        db.commit()
        return dispute_id
    finally:
        db.close()


def resolve_dispute(order_id: int, dispute_id: int, *, actor_id: Any, resolution: str) -> None:
    timer = _timer()
    resolution = str(resolution or "").strip()
    if not resolution:
        raise ValueError("請填寫爭議處理結果。")
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        now = timer.utc_iso()
        result = db.execute(text("""
            UPDATE vip_timer_disputes
            SET status='resolved', resolution=:resolution, resolved_by_discord_id=:actor, updated_at=:now
            WHERE id=:dispute_id AND order_id=:order_id AND status='open'
        """), {"resolution": resolution, "actor": str(actor_id or ""), "now": now, "dispute_id": int(dispute_id), "order_id": int(order_id)})
        if int(result.rowcount or 0) <= 0:
            raise ValueError("找不到尚未處理的爭議紀錄。")
        timer._event(db, int(order_id), "dispute_resolved", actor_id, {"dispute_id": int(dispute_id), "resolution": resolution})
        db.commit()
    finally:
        db.close()


def list_open_timer_operations() -> list[dict]:
    timer = _timer()
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        rows = db.execute(text("""
            SELECT s.order_id, s.customer_discord_id, s.status, s.current_rule_label,
                   s.started_at, s.ended_at, s.final_amount, s.updated_at,
                   s.vip_name_snapshot, s.vip_discount_pay_rate_snapshot,
                   o.bot_order_no, o.customer_display_name, o.ticket_channel_id
            FROM vip_timer_sessions s
            LEFT JOIN web_orders o ON o.id=s.order_id
            WHERE s.status IN ('waiting_staff','ready','running','paused','pending_payment')
            ORDER BY CASE s.status WHEN 'pending_payment' THEN 0 WHEN 'running' THEN 1 ELSE 2 END,
                     s.updated_at ASC
        """)).mappings().all()
        now = timer.utc_now()
        result = []
        for raw in rows:
            row = dict(raw)
            ended = timer.parse_dt(row.get("ended_at"))
            started = timer.parse_dt(row.get("started_at"))
            row["age_seconds"] = max(0, int((now - started).total_seconds())) if started else 0
            row["pending_age_seconds"] = max(0, int((now - ended).total_seconds())) if ended and row.get("status") == "pending_payment" else 0
            row["open_disputes"] = int(db.execute(text("SELECT COUNT(*) FROM vip_timer_disputes WHERE order_id=:order_id AND status='open'"), {"order_id": int(row["order_id"])}).scalar_one())
            result.append(row)
        return result
    finally:
        db.close()


def record_alert(order_id: int, alert_key: str, payload: dict | None = None) -> bool:
    timer = _timer()
    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        result = db.execute(text("""
            INSERT OR IGNORE INTO vip_timer_alerts(order_id,alert_key,payload_json,sent_at)
            VALUES (:order_id,:key,:payload,:sent_at)
        """), {
            "order_id": int(order_id), "key": str(alert_key),
            "payload": json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            "sent_at": timer.utc_iso(),
        })
        db.commit()
        return int(result.rowcount or 0) > 0
    finally:
        db.close()


__all__ = [
    "END_REQUEST_TTL_SECONDS",
    "clear_end_request",
    "correct_segment",
    "ensure_vip_timer_ops_tables",
    "get_end_request",
    "get_timer_detail",
    "get_vip_snapshot",
    "install_vip_timer_snapshot_guard",
    "list_open_timer_operations",
    "open_dispute",
    "recalculate_pending_settlement",
    "record_alert",
    "request_or_confirm_end",
    "resolve_dispute",
    "snapshot_vip_for_order",
]
