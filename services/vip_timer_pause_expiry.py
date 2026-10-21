from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text


PAUSE_REMINDER_SECONDS = 60 * 60
PAUSE_HARD_LIMIT_SECONDS = 2 * 60 * 60
PAUSE_EXTENSION_SECONDS = 2 * 60 * 60
_INSTALLED = False


def _timer():
    from services import vip_timer

    return vip_timer


def ensure_pause_expiry_tables(db=None) -> None:
    timer = _timer()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        timer.ensure_vip_timer_tables(db)
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS vip_timer_pause_extensions (
                order_id INTEGER PRIMARY KEY,
                extended_by_discord_id TEXT,
                extended_at TEXT NOT NULL,
                extension_until TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        if owns:
            db.commit()
    finally:
        if owns:
            db.close()


def get_pause_policy(order_id: int, db=None) -> dict:
    timer = _timer()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        ensure_pause_expiry_tables(db)
        row = db.execute(text("""
            SELECT status, paused_at
            FROM vip_timer_sessions
            WHERE order_id=:order_id
            LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()
        if row is None:
            raise ValueError("找不到 VIP 自由計時單。")

        status = str(row.get("status") or "")
        paused_at = timer.parse_dt(row.get("paused_at"))
        now = timer.utc_now()
        paused_seconds = 0
        if status == "paused" and paused_at is not None:
            paused_seconds = max(0, int((now - paused_at).total_seconds()))

        extension = db.execute(text("""
            SELECT extended_by_discord_id, extended_at, extension_until, reason
            FROM vip_timer_pause_extensions
            WHERE order_id=:order_id
            LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()
        extension = dict(extension) if extension is not None else None
        extension_until = timer.parse_dt((extension or {}).get("extension_until"))
        extension_active = bool(
            status == "paused"
            and extension_until is not None
            and now < extension_until
        )
        base_locked = status == "paused" and paused_seconds >= PAUSE_HARD_LIMIT_SECONDS
        resume_locked = bool(base_locked and not extension_active)
        reminder_due = bool(status == "paused" and paused_seconds >= PAUSE_REMINDER_SECONDS)

        return {
            "order_id": int(order_id),
            "status": status,
            "paused_at": str(row.get("paused_at") or ""),
            "paused_seconds": paused_seconds,
            "reminder_due": reminder_due,
            "resume_locked": resume_locked,
            "extension_used": extension is not None,
            "extension_active": extension_active,
            "extension_until": str((extension or {}).get("extension_until") or ""),
            "extended_by_discord_id": str((extension or {}).get("extended_by_discord_id") or ""),
            "extension_reason": str((extension or {}).get("reason") or ""),
        }
    finally:
        if owns:
            db.close()


def extend_pause_once(order_id: int, *, actor_id: Any, reason: str) -> dict:
    timer = _timer()
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("延長暫停必須填寫原因。")

    db = timer.SessionLocal()
    try:
        ensure_pause_expiry_tables(db)
        policy = get_pause_policy(int(order_id), db=db)
        if policy["status"] != "paused":
            raise ValueError("只有暫停中的自由計時單可以延長。")
        if policy["extension_used"]:
            raise ValueError("這張自由計時單已使用過一次暫停延長，不能再次延長。")

        now = timer.utc_now()
        until = now + timedelta(seconds=PAUSE_EXTENSION_SECONDS)
        now_text = timer.utc_iso(now)
        until_text = timer.utc_iso(until)
        db.execute(text("""
            INSERT INTO vip_timer_pause_extensions(
                order_id, extended_by_discord_id, extended_at, extension_until,
                reason, created_at, updated_at
            ) VALUES (
                :order_id, :actor, :now, :until, :reason, :now, :now
            )
        """), {
            "order_id": int(order_id),
            "actor": str(actor_id or ""),
            "now": now_text,
            "until": until_text,
            "reason": reason,
        })
        timer._event(db, int(order_id), "pause_extension_granted", actor_id, {
            "extension_seconds": PAUSE_EXTENSION_SECONDS,
            "extension_until": until_text,
            "reason": reason,
        })
        db.commit()
        return get_pause_policy(int(order_id))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def assert_resume_allowed(order_id: int) -> dict:
    policy = get_pause_policy(int(order_id))
    if policy["resume_locked"]:
        raise ValueError(
            "這張 VIP 自由計時已暫停超過 2 小時，不能直接繼續。"
            "請由老闆與陪玩雙方確認結束並完成結算；特殊情況請聯繫客服。"
        )
    return policy


def install_vip_timer_pause_expiry() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    ensure_pause_expiry_tables()

    from services import vip_timer_runtime as runtime

    original_resume = runtime.resume_timer

    def guarded_resume(order_id: int, actor_id: Any):
        assert_resume_allowed(int(order_id))
        return original_resume(int(order_id), actor_id)

    runtime.resume_timer = guarded_resume
    _INSTALLED = True


__all__ = [
    "PAUSE_EXTENSION_SECONDS",
    "PAUSE_HARD_LIMIT_SECONDS",
    "PAUSE_REMINDER_SECONDS",
    "assert_resume_allowed",
    "ensure_pause_expiry_tables",
    "extend_pause_once",
    "get_pause_policy",
    "install_vip_timer_pause_expiry",
]
