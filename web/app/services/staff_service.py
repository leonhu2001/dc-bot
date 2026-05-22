import json
from datetime import datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.staff_models import WebStaffMember
from web.app.config import config

DISCORD_API_BASE = "https://discord.com/api/v10"


def get_staff_display_name(member: WebStaffMember) -> str:
    return str(
        member.display_name
        or member.global_name
        or member.username
        or member.discord_id
    )


def get_staff_member_by_id(
    db: Session,
    *,
    discord_id: str,
) -> WebStaffMember | None:
    return db.get(WebStaffMember, str(discord_id))


def list_customer_service_members(db: Session) -> list[WebStaffMember]:
    statement = (
        select(WebStaffMember)
        .where(WebStaffMember.is_active.is_(True))
        .where(WebStaffMember.is_customer_service.is_(True))
        .order_by(WebStaffMember.display_name.asc(), WebStaffMember.username.asc())
    )

    return list(db.scalars(statement).all())


def list_worker_members(db: Session) -> list[WebStaffMember]:
    statement = (
        select(WebStaffMember)
        .where(WebStaffMember.is_active.is_(True))
        .where(WebStaffMember.is_worker.is_(True))
        .where(WebStaffMember.is_companion.is_(False))
        .order_by(WebStaffMember.display_name.asc(), WebStaffMember.username.asc())
    )

    return list(db.scalars(statement).all())


def list_companion_members(db: Session) -> list[WebStaffMember]:
    statement = (
        select(WebStaffMember)
        .where(WebStaffMember.is_active.is_(True))
        .where(WebStaffMember.is_companion.is_(True))
        .order_by(WebStaffMember.display_name.asc(), WebStaffMember.username.asc())
    )

    return list(db.scalars(statement).all())


def upsert_staff_member(
    db: Session,
    *,
    discord_id: str,
    username: str | None,
    display_name: str | None,
    global_name: str | None,
    avatar: str | None,
    role_ids: list[str],
    is_customer_service: bool,
    is_worker: bool,
    is_companion: bool,
    synced_at: datetime | None = None,
) -> WebStaffMember:
    synced_at = synced_at or datetime.utcnow()
    discord_id = str(discord_id)
    role_ids = [str(role_id) for role_id in role_ids]

    member = db.get(WebStaffMember, discord_id)

    if member is None:
        member = WebStaffMember(discord_id=discord_id)
        db.add(member)

    member.username = username
    member.display_name = display_name
    member.global_name = global_name
    member.avatar = avatar
    member.roles_json = json.dumps(role_ids, ensure_ascii=False)
    member.is_customer_service = bool(is_customer_service)
    member.is_worker = bool(is_worker)
    member.is_companion = bool(is_companion)
    member.is_active = True
    member.last_synced_at = synced_at

    return member


def sync_staff_members_from_discord(db: Session) -> dict:
    if not config.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")

    if not config.DISCORD_GUILD_ID:
        raise RuntimeError("DISCORD_GUILD_ID is not configured")

    customer_service_role_ids = {str(role_id) for role_id in config.ADMIN_ROLE_IDS}
    worker_role_ids = {str(role_id) for role_id in config.WORKER_ROLE_IDS}
    companion_role_ids = {str(role_id) for role_id in config.COMPANION_ROLE_IDS}

    # 陪玩不要混進打手。即使 .env 的 WORKER_ROLE_IDS 不小心包含陪玩身分組，這裡也會自動排除。
    pure_worker_role_ids = worker_role_ids - companion_role_ids
    all_target_role_ids = customer_service_role_ids | pure_worker_role_ids | companion_role_ids

    synced_at = datetime.utcnow()
    after = "0"
    total_seen = 0
    synced_count = 0
    synced_ids: set[str] = set()

    while True:
        response = requests.get(
            f"{DISCORD_API_BASE}/guilds/{config.DISCORD_GUILD_ID}/members",
            headers={"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"},
            params={"limit": 1000, "after": after},
            timeout=30,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Discord member sync failed: {response.status_code} {response.text}")

        members = response.json()

        if not members:
            break

        for member_data in members:
            total_seen += 1
            user_data = member_data.get("user") or {}
            discord_id = str(user_data.get("id") or "")

            if not discord_id:
                continue

            role_ids = [str(role_id) for role_id in member_data.get("roles", [])]
            role_set = set(role_ids)

            if not (role_set & all_target_role_ids):
                continue

            is_customer_service = bool(role_set & customer_service_role_ids)
            is_companion = bool(role_set & companion_role_ids)
            is_worker = bool(role_set & pure_worker_role_ids)

            display_name = (
                member_data.get("nick")
                or user_data.get("global_name")
                or user_data.get("username")
                or discord_id
            )

            upsert_staff_member(
                db,
                discord_id=discord_id,
                username=user_data.get("username"),
                display_name=display_name,
                global_name=user_data.get("global_name"),
                avatar=user_data.get("avatar"),
                role_ids=role_ids,
                is_customer_service=is_customer_service,
                is_worker=is_worker,
                is_companion=is_companion,
                synced_at=synced_at,
            )

            synced_ids.add(discord_id)
            synced_count += 1

        after = str((members[-1].get("user") or {}).get("id") or after)

        if len(members) < 1000:
            break

    existing_members = list(db.scalars(select(WebStaffMember)).all())
    disabled_count = 0

    for member in existing_members:
        if member.discord_id not in synced_ids:
            if member.is_active:
                disabled_count += 1
            member.is_active = False
            member.last_synced_at = synced_at

    db.commit()

    return {
        "total_seen": total_seen,
        "synced_count": synced_count,
        "disabled_count": disabled_count,
    }
