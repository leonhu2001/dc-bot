from __future__ import annotations

import json
from datetime import datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.time_utils import utc_now_naive
from shared.staff_models import StaffStoreBinding, WebStaffMember
from web.app.config import config


DISCORD_API_BASE = "https://discord.com/api/v10"
STORE_BOUND_ROLE_ID = "1503828415063785634"
STORE_BINDING_BONUS_RATE = 0.03
STORE_BINDING_MAX_RATE = 0.90

ACTIVE = "active"
PENDING = "pending"
ENDED = "ended"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"


def _actor_display_name(user: dict | None) -> str:
    user = user or {}
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("name")
        or user.get("id")
        or "未知人員"
    )


def _current_rows(db: Session, staff_discord_id: str) -> list[StaffStoreBinding]:
    return list(
        db.scalars(
            select(StaffStoreBinding)
            .where(StaffStoreBinding.staff_discord_id == str(staff_discord_id))
            .order_by(StaffStoreBinding.id.desc())
        ).all()
    )


def get_active_binding(db: Session, staff_discord_id: str) -> StaffStoreBinding | None:
    return db.scalar(
        select(StaffStoreBinding)
        .where(StaffStoreBinding.staff_discord_id == str(staff_discord_id))
        .where(StaffStoreBinding.status == ACTIVE)
        .order_by(StaffStoreBinding.id.desc())
        .limit(1)
    )


def get_pending_binding(db: Session, staff_discord_id: str) -> StaffStoreBinding | None:
    return db.scalar(
        select(StaffStoreBinding)
        .where(StaffStoreBinding.staff_discord_id == str(staff_discord_id))
        .where(StaffStoreBinding.status == PENDING)
        .order_by(StaffStoreBinding.id.desc())
        .limit(1)
    )


def get_latest_binding(db: Session, staff_discord_id: str) -> StaffStoreBinding | None:
    rows = _current_rows(db, staff_discord_id)
    return rows[0] if rows else None


def binding_payload(binding: StaffStoreBinding | None) -> dict:
    if binding is None:
        return {
            "status": "none",
            "status_label": "未綁店",
            "source": None,
            "requested_at": None,
            "started_at": None,
            "ended_at": None,
            "reviewed_by": None,
            "discord_sync_status": "not_required",
            "discord_sync_error": None,
            "bonus_rate": STORE_BINDING_BONUS_RATE,
            "max_rate": STORE_BINDING_MAX_RATE,
        }

    status_label = {
        PENDING: "待審核",
        ACTIVE: "綁店中",
        ENDED: "已解除",
        REJECTED: "未通過",
        WITHDRAWN: "已撤回",
    }.get(str(binding.status), str(binding.status))

    def iso(value: datetime | None):
        return value.isoformat() if value is not None else None

    return {
        "id": int(binding.id),
        "staff_discord_id": str(binding.staff_discord_id),
        "status": str(binding.status),
        "status_label": status_label,
        "source": str(binding.source or ""),
        "requested_at": iso(binding.requested_at),
        "started_at": iso(binding.started_at),
        "ended_at": iso(binding.ended_at),
        "reviewed_by": binding.reviewed_by_display_name,
        "reviewed_at": iso(binding.reviewed_at),
        "note": binding.note,
        "discord_sync_status": str(binding.discord_sync_status or "not_required"),
        "discord_sync_error": binding.discord_sync_error,
        "discord_synced_at": iso(binding.discord_synced_at),
        "bonus_rate": STORE_BINDING_BONUS_RATE,
        "max_rate": STORE_BINDING_MAX_RATE,
    }


def get_staff_binding_payload(db: Session, staff_discord_id: str) -> dict:
    active = get_active_binding(db, staff_discord_id)
    if active is not None:
        return binding_payload(active)
    pending = get_pending_binding(db, staff_discord_id)
    if pending is not None:
        return binding_payload(pending)
    return binding_payload(get_latest_binding(db, staff_discord_id))


def _ensure_binding_candidate(db: Session, staff_discord_id: str) -> WebStaffMember:
    member = db.get(WebStaffMember, str(staff_discord_id))
    if member is None or not bool(member.is_active) or not bool(member.is_worker):
        raise ValueError("只有目前啟用中的可接單人員可以取得綁店資格。")
    return member


def apply_for_store_binding(db: Session, *, staff_discord_id: str) -> StaffStoreBinding:
    _ensure_binding_candidate(db, staff_discord_id)
    if get_active_binding(db, staff_discord_id) is not None:
        raise ValueError("你目前已經是綁店人員。")
    if get_pending_binding(db, staff_discord_id) is not None:
        raise ValueError("你已經有一筆綁店申請正在審核中。")

    row = StaffStoreBinding(
        staff_discord_id=str(staff_discord_id),
        status=PENDING,
        source="self_application",
        requested_at=utc_now_naive(),
        discord_sync_status="not_required",
    )
    db.add(row)
    db.flush()
    return row


def withdraw_store_binding_application(db: Session, *, staff_discord_id: str) -> StaffStoreBinding:
    row = get_pending_binding(db, staff_discord_id)
    if row is None:
        raise ValueError("目前沒有可撤回的綁店申請。")
    row.status = WITHDRAWN
    row.ended_at = utc_now_naive()
    row.discord_sync_status = "not_required"
    db.flush()
    return row


def _sync_cached_role(db: Session, staff_discord_id: str, enabled: bool) -> None:
    member = db.get(WebStaffMember, str(staff_discord_id))
    if member is None:
        return
    try:
        role_ids = {str(value) for value in json.loads(member.roles_json or "[]")}
    except Exception:
        role_ids = set()
    if enabled:
        role_ids.add(STORE_BOUND_ROLE_ID)
    else:
        role_ids.discard(STORE_BOUND_ROLE_ID)
    member.roles_json = json.dumps(sorted(role_ids), ensure_ascii=False)


def sync_store_binding_role(
    db: Session,
    *,
    binding: StaffStoreBinding,
    enabled: bool,
) -> bool:
    binding.discord_sync_status = "pending"
    binding.discord_sync_error = None
    guild_id = str(getattr(config, "DISCORD_GUILD_ID", "") or "").strip()
    bot_token = str(getattr(config, "DISCORD_BOT_TOKEN", "") or "").strip()

    if not guild_id or not bot_token:
        binding.discord_sync_status = "error"
        binding.discord_sync_error = "Discord Bot 或 Guild 設定不完整。"
        return False

    method = requests.put if enabled else requests.delete
    try:
        response = method(
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{binding.staff_discord_id}/roles/{STORE_BOUND_ROLE_ID}",
            headers={
                "Authorization": f"Bot {bot_token}",
                "X-Audit-Log-Reason": "Mowan store binding sync",
            },
            timeout=15,
        )
        if response.status_code != 204:
            raise RuntimeError(f"Discord HTTP {response.status_code}")
    except Exception as exc:
        binding.discord_sync_status = "error"
        binding.discord_sync_error = str(exc)[:500]
        return False

    binding.discord_sync_status = "synced"
    binding.discord_sync_error = None
    binding.discord_synced_at = utc_now_naive()
    _sync_cached_role(db, binding.staff_discord_id, enabled)
    return True


def grant_store_binding(
    db: Session,
    *,
    staff_discord_id: str,
    actor: dict,
    source: str = "staff_granted",
    note: str | None = None,
) -> StaffStoreBinding:
    _ensure_binding_candidate(db, staff_discord_id)
    existing = get_active_binding(db, staff_discord_id)
    if existing is not None:
        raise ValueError("這位人員目前已經是綁店狀態。")

    now = utc_now_naive()
    row = get_pending_binding(db, staff_discord_id)
    if row is None:
        row = StaffStoreBinding(
            staff_discord_id=str(staff_discord_id),
            requested_at=now,
            source=str(source or "staff_granted"),
        )
        db.add(row)
    elif source == "staff_granted":
        row.source = "staff_granted"

    row.status = ACTIVE
    row.started_at = now
    row.ended_at = None
    row.reviewed_by_discord_id = str(actor.get("id") or "")
    row.reviewed_by_display_name = _actor_display_name(actor)
    row.reviewed_at = now
    row.note = str(note or "").strip()[:1000] or None
    db.flush()
    sync_store_binding_role(db, binding=row, enabled=True)
    db.flush()
    return row


def reject_store_binding(
    db: Session,
    *,
    staff_discord_id: str,
    actor: dict,
    note: str | None = None,
) -> StaffStoreBinding:
    row = get_pending_binding(db, staff_discord_id)
    if row is None:
        raise ValueError("找不到待審核的綁店申請。")
    now = utc_now_naive()
    row.status = REJECTED
    row.ended_at = now
    row.reviewed_by_discord_id = str(actor.get("id") or "")
    row.reviewed_by_display_name = _actor_display_name(actor)
    row.reviewed_at = now
    row.note = str(note or "").strip()[:1000] or None
    row.discord_sync_status = "not_required"
    db.flush()
    return row


def end_store_binding(
    db: Session,
    *,
    staff_discord_id: str,
    actor: dict,
    note: str | None = None,
) -> StaffStoreBinding:
    row = get_active_binding(db, staff_discord_id)
    if row is None:
        raise ValueError("這位人員目前沒有有效的綁店資格。")
    now = utc_now_naive()
    row.status = ENDED
    row.ended_at = now
    row.reviewed_by_discord_id = str(actor.get("id") or "")
    row.reviewed_by_display_name = _actor_display_name(actor)
    row.reviewed_at = now
    row.note = str(note or "").strip()[:1000] or None
    db.flush()
    sync_store_binding_role(db, binding=row, enabled=False)
    db.flush()
    return row


def list_binding_rows(db: Session, *, status: str | None = None) -> list[StaffStoreBinding]:
    statement = select(StaffStoreBinding)
    if status:
        statement = statement.where(StaffStoreBinding.status == str(status))
    statement = statement.order_by(StaffStoreBinding.id.desc())
    return list(db.scalars(statement).all())


def list_binding_candidates(db: Session) -> list[WebStaffMember]:
    active_ids = {
        str(row.staff_discord_id)
        for row in list_binding_rows(db, status=ACTIVE)
    }
    members = list(
        db.scalars(
            select(WebStaffMember)
            .where(WebStaffMember.is_active.is_(True))
            .where(WebStaffMember.is_worker.is_(True))
            .order_by(WebStaffMember.display_name.asc(), WebStaffMember.username.asc())
        ).all()
    )
    return [member for member in members if str(member.discord_id) not in active_ids]


def member_display_name(member: WebStaffMember | None, fallback: str = "") -> str:
    if member is None:
        return str(fallback or "")
    return str(
        member.display_name
        or member.global_name
        or member.username
        or member.discord_id
    )
