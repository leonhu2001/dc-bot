from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

from services.order_product_status import is_order_product_active
from services.order_rules import CATEGORY_LABELS, ORDER_RULES
from shared.db import SessionLocal


VIP_TIMER_MARKER = "VIP_TIMER"
VIP_TIMER_CATEGORY = "vip_timer"
VIP_TIMER_CATEGORY_LABEL = "VIP 自由計時"
VIP_TIMER_PREFIX = "vip_timer__"
VIP_TIMER_OPEN_STATUSES = {
    "waiting_staff",
    "ready",
    "running",
    "paused",
    "pending_payment",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def parse_dt(value: Any) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        result = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def ensure_vip_timer_tables(db=None) -> None:
    owns = db is None
    if owns:
        db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_sessions (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT NOT NULL,
                ticket_channel_id TEXT,
                timer_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'waiting_staff',
                current_rule_key TEXT NOT NULL,
                current_rule_label TEXT NOT NULL,
                current_category_label TEXT NOT NULL,
                current_hourly_rate INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                paused_at TEXT,
                ended_at TEXT,
                final_amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                rule_key TEXT NOT NULL,
                rule_label TEXT NOT NULL,
                category_label TEXT NOT NULL,
                hourly_rate INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                active_started_at TEXT,
                ended_at TEXT,
                billable_seconds INTEGER NOT NULL DEFAULT 0,
                actor_discord_id TEXT,
                staff_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(order_id, seq)
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor_discord_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_vip_timer_customer_status ON vip_timer_sessions(customer_discord_id, status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_vip_timer_segments_order ON vip_timer_segments(order_id, seq)"))
        if owns:
            db.commit()
    finally:
        if owns:
            db.close()


def strip_vip_timer_rule_key(rule_key: Any) -> str:
    key = str(rule_key or "").strip()
    return key[len(VIP_TIMER_PREFIX):] if key.startswith(VIP_TIMER_PREFIX) else key


def is_vip_timer_rule_key(rule_key: Any) -> bool:
    return str(rule_key or "").strip().startswith(VIP_TIMER_PREFIX)


def is_vip_timer_order_data(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    if bool(data.get("vip_timer_order")):
        return True
    return VIP_TIMER_MARKER in str(data.get("web_order_note") or data.get("note") or "")


def public_hourly_rules() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, rule in ORDER_RULES.items():
        key = str(key or "").strip()
        if not key or str(getattr(rule, "pricing_type", "")) != "hourly":
            continue
        if not is_order_product_active(key):
            continue
        price = int(getattr(rule, "price", 0) or 0)
        if price <= 0:
            continue
        rows.append({
            "rule_key": key,
            "label": str(getattr(rule, "label", key) or key),
            "category": str(getattr(rule, "category", "") or ""),
            "category_label": CATEGORY_LABELS.get(str(getattr(rule, "category", "") or ""), str(getattr(rule, "category", "") or "未分類")),
            "hourly_rate": price,
            "player_count_enabled": bool(getattr(rule, "player_count_enabled", False)),
            "min_player_count": int(getattr(rule, "min_player_count", 1) or 1),
            "max_player_count": int(getattr(rule, "max_player_count", 8) or 8),
            "allow_specify": bool(getattr(rule, "allow_specify", False)),
        })
    rows.sort(key=lambda row: (row["category_label"], row["label"], row["rule_key"]))
    return rows


def rule_snapshot(rule_key: str) -> dict[str, Any]:
    key = strip_vip_timer_rule_key(rule_key)
    rule = ORDER_RULES.get(key)
    if rule is None or str(getattr(rule, "pricing_type", "")) != "hourly":
        raise ValueError("VIP 自由計時只能選擇以小時計價的方案。")
    if not is_order_product_active(key):
        raise ValueError("這個玩法目前已下架，請改選其他玩法。")
    price = int(getattr(rule, "price", 0) or 0)
    if price <= 0:
        raise ValueError("這個玩法目前沒有有效的小時價格。")
    category = str(getattr(rule, "category", "") or "")
    return {
        "rule_key": key,
        "rule_label": str(getattr(rule, "label", key) or key),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, category or "未分類"),
        "hourly_rate": price,
    }


def _event(db, order_id: int, action: str, actor_id: Any = None, payload: dict | None = None) -> None:
    db.execute(text("""
        INSERT INTO vip_timer_events(order_id, action, actor_discord_id, payload_json, created_at)
        VALUES (:order_id, :action, :actor, :payload, :created_at)
    """), {
        "order_id": int(order_id),
        "action": str(action),
        "actor": str(actor_id or ""),
        "payload": json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        "created_at": utc_iso(),
    })


def reconcile_customer_sessions(db, customer_id: str) -> None:
    rows = db.execute(text("""
        SELECT s.order_id, s.status, o.status AS order_status
        FROM vip_timer_sessions s
        LEFT JOIN web_orders o ON o.id = s.order_id
        WHERE s.customer_discord_id = :customer_id
          AND s.status = 'pending_payment'
    """), {"customer_id": str(customer_id)}).mappings().all()
    for row in rows:
        if str(row.get("order_status") or "").lower() in {"active", "closed"}:
            db.execute(text("UPDATE vip_timer_sessions SET status='paid', updated_at=:now WHERE order_id=:order_id"), {
                "now": utc_iso(), "order_id": int(row["order_id"]),
            })


def has_open_vip_timer(customer_id: str, *, exclude_order_id: int | None = None) -> bool:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        reconcile_customer_sessions(db, str(customer_id))
        params: dict[str, Any] = {"customer_id": str(customer_id)}
        extra = ""
        if exclude_order_id is not None:
            extra = " AND order_id <> :exclude_order_id"
            params["exclude_order_id"] = int(exclude_order_id)
        row = db.execute(text(
            "SELECT 1 FROM vip_timer_sessions WHERE customer_discord_id=:customer_id "
            "AND status IN ('waiting_staff','ready','running','paused','pending_payment')" + extra + " LIMIT 1"
        ), params).first()
        db.commit()
        return row is not None
    finally:
        db.close()


def create_vip_timer_session(db, *, order_id: int, customer_id: str, initial_rule_key: str) -> dict[str, Any]:
    ensure_vip_timer_tables(db)
    reconcile_customer_sessions(db, str(customer_id))
    existing = db.execute(text("""
        SELECT order_id FROM vip_timer_sessions
        WHERE customer_discord_id=:customer_id
          AND status IN ('waiting_staff','ready','running','paused','pending_payment')
          AND order_id <> :order_id
        LIMIT 1
    """), {"customer_id": str(customer_id), "order_id": int(order_id)}).first()
    if existing is not None:
        raise ValueError("你目前已有一張進行中或待付款的 VIP 自由計時單，請先完成上一張。")
    snap = rule_snapshot(initial_rule_key)
    now = utc_iso()
    db.execute(text("""
        INSERT INTO vip_timer_sessions(
            order_id, customer_discord_id, status, current_rule_key, current_rule_label,
            current_category_label, current_hourly_rate, final_amount, created_at, updated_at
        ) VALUES (
            :order_id, :customer_id, 'waiting_staff', :rule_key, :rule_label,
            :category_label, :rate, 0, :now, :now
        )
        ON CONFLICT(order_id) DO UPDATE SET
            current_rule_key=excluded.current_rule_key,
            current_rule_label=excluded.current_rule_label,
            current_category_label=excluded.current_category_label,
            current_hourly_rate=excluded.current_hourly_rate,
            updated_at=excluded.updated_at
    """), {
        "order_id": int(order_id), "customer_id": str(customer_id),
        "rule_key": snap["rule_key"], "rule_label": snap["rule_label"],
        "category_label": snap["category_label"], "rate": snap["hourly_rate"], "now": now,
    })
    _event(db, order_id, "created", customer_id, snap)
    return snap


def get_session(order_id: int, db=None) -> dict[str, Any] | None:
    owns = db is None
    if owns:
        db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        row = db.execute(text("SELECT * FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1"), {"order_id": int(order_id)}).mappings().first()
        return dict(row) if row else None
    finally:
        if owns:
            db.close()


def get_session_by_ticket(ticket_channel_id: int | str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        row = db.execute(text("SELECT * FROM vip_timer_sessions WHERE ticket_channel_id=:channel_id ORDER BY order_id DESC LIMIT 1"), {"channel_id": str(ticket_channel_id)}).mappings().first()
        return dict(row) if row else None
    finally:
        db.close()


def attach_ticket(order_id: int, *, ticket_channel_id: int | str, timer_message_id: int | str | None = None) -> None:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        db.execute(text("""
            UPDATE vip_timer_sessions
            SET ticket_channel_id=:channel_id,
                timer_message_id=COALESCE(:message_id, timer_message_id),
                status=CASE WHEN status='waiting_staff' THEN 'ready' ELSE status END,
                updated_at=:now
            WHERE order_id=:order_id
        """), {"channel_id": str(ticket_channel_id), "message_id": str(timer_message_id) if timer_message_id else None, "now": utc_iso(), "order_id": int(order_id)})
        db.commit()
    finally:
        db.close()


def _current_segment(db, order_id: int) -> dict[str, Any] | None:
    row = db.execute(text("SELECT * FROM vip_timer_segments WHERE order_id=:order_id AND ended_at IS NULL ORDER BY seq DESC LIMIT 1"), {"order_id": int(order_id)}).mappings().first()
    return dict(row) if row else None


def _accrue_segment(db, segment: dict[str, Any], now: datetime) -> int:
    active_start = parse_dt(segment.get("active_started_at"))
    seconds = int(segment.get("billable_seconds") or 0)
    if active_start is not None:
        seconds += max(0, int((now - active_start).total_seconds()))
    db.execute(text("UPDATE vip_timer_segments SET billable_seconds=:seconds, active_started_at=NULL, updated_at=:now WHERE id=:id"), {
        "seconds": seconds, "now": utc_iso(now), "id": int(segment["id"]),
    })
    return seconds


def start_timer(order_id: int, actor_id: Any, staff_ids: list[str] | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        session = get_session(order_id, db)
        if not session or session["status"] not in {"waiting_staff", "ready"}:
            raise ValueError("這張計時單目前不能開始計時。")
        now = utc_now(); now_text = utc_iso(now)
        seq = int(db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM vip_timer_segments WHERE order_id=:order_id"), {"order_id": int(order_id)}).scalar_one())
        db.execute(text("""
            INSERT INTO vip_timer_segments(order_id, seq, rule_key, rule_label, category_label, hourly_rate,
                started_at, active_started_at, billable_seconds, actor_discord_id, staff_ids_json, created_at, updated_at)
            VALUES (:order_id,:seq,:rule_key,:rule_label,:category_label,:rate,:now,:now,0,:actor,:staff,:now,:now)
        """), {
            "order_id": int(order_id), "seq": seq, "rule_key": session["current_rule_key"],
            "rule_label": session["current_rule_label"], "category_label": session["current_category_label"],
            "rate": int(session["current_hourly_rate"]), "now": now_text, "actor": str(actor_id or ""),
            "staff": json.dumps(staff_ids or [], ensure_ascii=False),
        })
        db.execute(text("UPDATE vip_timer_sessions SET status='running', started_at=COALESCE(started_at,:now), paused_at=NULL, updated_at=:now WHERE order_id=:order_id"), {"now": now_text, "order_id": int(order_id)})
        _event(db, order_id, "start", actor_id, {"rule_key": session["current_rule_key"]})
        db.commit()
        return get_session(order_id) or {}
    finally:
        db.close()


def pause_timer(order_id: int, actor_id: Any) -> dict[str, Any]:
    db = SessionLocal()
    try:
        session = get_session(order_id, db)
        if not session or session["status"] != "running":
            raise ValueError("目前不是計時中狀態。")
        segment = _current_segment(db, order_id)
        if not segment:
            raise ValueError("找不到目前計時區段。")
        now = utc_now(); _accrue_segment(db, segment, now)
        db.execute(text("UPDATE vip_timer_sessions SET status='paused', paused_at=:now, updated_at=:now WHERE order_id=:order_id"), {"now": utc_iso(now), "order_id": int(order_id)})
        _event(db, order_id, "pause", actor_id)
        db.commit(); return get_session(order_id) or {}
    finally:
        db.close()


def resume_timer(order_id: int, actor_id: Any) -> dict[str, Any]:
    db = SessionLocal()
    try:
        session = get_session(order_id, db)
        if not session or session["status"] != "paused":
            raise ValueError("目前不是暫停狀態。")
        segment = _current_segment(db, order_id)
        if not segment:
            raise ValueError("找不到目前計時區段。")
        now_text = utc_iso()
        db.execute(text("UPDATE vip_timer_segments SET active_started_at=:now, updated_at=:now WHERE id=:id"), {"now": now_text, "id": int(segment["id"])})
        db.execute(text("UPDATE vip_timer_sessions SET status='running', paused_at=NULL, updated_at=:now WHERE order_id=:order_id"), {"now": now_text, "order_id": int(order_id)})
        _event(db, order_id, "resume", actor_id)
        db.commit(); return get_session(order_id) or {}
    finally:
        db.close()


def switch_rule(order_id: int, new_rule_key: str, actor_id: Any, staff_ids: list[str] | None = None) -> dict[str, Any]:
    snap = rule_snapshot(new_rule_key)
    db = SessionLocal()
    try:
        session = get_session(order_id, db)
        if not session or session["status"] not in {"running", "paused"}:
            raise ValueError("只有計時中或暫停中的訂單可以切換玩法。")
        now = utc_now(); now_text = utc_iso(now)
        segment = _current_segment(db, order_id)
        if segment:
            if session["status"] == "running":
                _accrue_segment(db, segment, now)
            db.execute(text("UPDATE vip_timer_segments SET ended_at=:now, updated_at=:now WHERE id=:id"), {"now": now_text, "id": int(segment["id"])})
        seq = int(db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM vip_timer_segments WHERE order_id=:order_id"), {"order_id": int(order_id)}).scalar_one())
        active_started_at = now_text if session["status"] == "running" else None
        db.execute(text("""
            INSERT INTO vip_timer_segments(order_id, seq, rule_key, rule_label, category_label, hourly_rate,
                started_at, active_started_at, billable_seconds, actor_discord_id, staff_ids_json, created_at, updated_at)
            VALUES (:order_id,:seq,:rule_key,:rule_label,:category_label,:rate,:now,:active,0,:actor,:staff,:now,:now)
        """), {
            "order_id": int(order_id), "seq": seq, "rule_key": snap["rule_key"], "rule_label": snap["rule_label"],
            "category_label": snap["category_label"], "rate": snap["hourly_rate"], "now": now_text,
            "active": active_started_at, "actor": str(actor_id or ""), "staff": json.dumps(staff_ids or [], ensure_ascii=False),
        })
        db.execute(text("""
            UPDATE vip_timer_sessions SET current_rule_key=:rule_key, current_rule_label=:rule_label,
                current_category_label=:category_label, current_hourly_rate=:rate, updated_at=:now WHERE order_id=:order_id
        """), {**snap, "rate": snap["hourly_rate"], "now": now_text, "order_id": int(order_id)})
        _event(db, order_id, "switch", actor_id, snap)
        db.commit(); return get_session(order_id) or {}
    finally:
        db.close()


def list_segments(order_id: int) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        return [dict(row) for row in db.execute(text("SELECT * FROM vip_timer_segments WHERE order_id=:order_id ORDER BY seq ASC"), {"order_id": int(order_id)}).mappings().all()]
    finally:
        db.close()


def calculate_total(order_id: int, db=None) -> tuple[int, int]:
    owns = db is None
    if owns: db = SessionLocal()
    try:
        rows = db.execute(text("SELECT hourly_rate, billable_seconds FROM vip_timer_segments WHERE order_id=:order_id"), {"order_id": int(order_id)}).mappings().all()
        total_seconds = sum(max(0, int(row["billable_seconds"] or 0)) for row in rows)
        amount = sum(Decimal(int(row["hourly_rate"] or 0)) * Decimal(max(0, int(row["billable_seconds"] or 0))) / Decimal(3600) for row in rows)
        rounded = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return rounded, total_seconds
    finally:
        if owns: db.close()


def end_timer(order_id: int, actor_id: Any) -> dict[str, Any]:
    db = SessionLocal()
    try:
        session = get_session(order_id, db)
        if not session or session["status"] not in {"running", "paused"}:
            raise ValueError("目前沒有可結束的計時。")
        now = utc_now(); now_text = utc_iso(now)
        segment = _current_segment(db, order_id)
        if segment:
            if session["status"] == "running":
                _accrue_segment(db, segment, now)
            db.execute(text("UPDATE vip_timer_segments SET ended_at=:now, updated_at=:now WHERE id=:id"), {"now": now_text, "id": int(segment["id"])})
        amount, total_seconds = calculate_total(order_id, db)
        breakdown = [dict(row) for row in db.execute(text("SELECT seq, rule_key, rule_label, category_label, hourly_rate, billable_seconds, started_at, ended_at FROM vip_timer_segments WHERE order_id=:order_id ORDER BY seq"), {"order_id": int(order_id)}).mappings().all()]
        snapshot = {"vip_timer": True, "total_seconds": total_seconds, "final_amount": amount, "segments": breakdown, "ended_at": now_text}
        db.execute(text("""
            UPDATE vip_timer_sessions SET status='pending_payment', ended_at=:now, paused_at=NULL,
                final_amount=:amount, updated_at=:now WHERE order_id=:order_id
        """), {"now": now_text, "amount": amount, "order_id": int(order_id)})
        db.execute(text("""
            UPDATE web_orders SET amount=:amount, original_amount=:amount, payout_base_amount=:amount,
                customer_pay_amount=:amount, payment_method='待付款', price_snapshot_json=:snapshot,
                updated_at=CURRENT_TIMESTAMP WHERE id=:order_id
        """), {"amount": amount, "snapshot": json.dumps(snapshot, ensure_ascii=False, sort_keys=True), "order_id": int(order_id)})
        db.execute(text("UPDATE order_acceptance_meta SET price_snapshot_json=:snapshot, updated_at=CURRENT_TIMESTAMP WHERE order_id=:order_id"), {"snapshot": json.dumps(snapshot, ensure_ascii=False, sort_keys=True), "order_id": int(order_id)})
        _event(db, order_id, "end", actor_id, {"final_amount": amount, "total_seconds": total_seconds})
        db.commit()
        return {"order_id": int(order_id), "final_amount": amount, "total_seconds": total_seconds, "segments": breakdown}
    finally:
        db.close()
