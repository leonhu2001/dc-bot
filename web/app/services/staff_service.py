import json
from datetime import datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember
from services.game_roles import GAME_ROLE_IDS
from web.app.config import config
from web.app.services.role_catalog import (
    CUSTOMER_SERVICE_ROLE_ID,
    COMPANION_ROLE_IDS,
    PROTECTOR_ROLE_IDS,
    RECEIVER_ROLE_IDS,
    is_companion as catalog_is_companion,
    is_customer_service as catalog_is_customer_service,
    is_protector,
    normalize_role_ids,
)

DISCORD_API_BASE = "https://discord.com/api/v10"

WORKER_ROLE_IDS = {
    "1500234130871550004",
    "1500234170943934544",
    "1500751039060643990",
}
COMPANION_ROLE_IDS = {
    "1500751059239440575",
    "1482080315798192210",
}

# 舊變數保留相容用，實際分類使用上面的 set。
WORKER_ROLE_ID = next(iter(WORKER_ROLE_IDS))
COMPANION_ROLE_ID = next(iter(COMPANION_ROLE_IDS))



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


def classify_roles(role_ids: list[str]) -> tuple[bool, bool, bool]:
    role_set = normalize_role_ids(role_ids)

    customer_service_role_ids = normalize_role_ids(
        getattr(config, "CUSTOMER_SERVICE_ROLE_IDS", set())
    )

    is_customer_service = catalog_is_customer_service(role_set, customer_service_role_ids)
    is_worker = is_protector(role_set) or catalog_is_companion(role_set) or bool(role_set & GAME_ROLE_IDS)
    is_companion = catalog_is_companion(role_set)

    return is_customer_service, is_worker, is_companion


def upsert_staff_member(
    db: Session,
    *,
    discord_id: str,
    username: str | None,
    display_name: str | None,
    global_name: str | None,
    avatar: str | None,
    role_ids: list[str],
    synced_at: datetime | None = None,
) -> WebStaffMember:
    synced_at = synced_at or datetime.utcnow()
    discord_id = str(discord_id)
    role_ids = [str(role_id) for role_id in role_ids]

    is_customer_service, is_worker, is_companion = classify_roles(role_ids)

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
    member.is_active = bool(is_customer_service or is_worker or is_companion)
    member.last_synced_at = synced_at

    return member


def sync_staff_members_from_discord(db=None) -> dict:
    owns_session = db is None

    if owns_session:
        db = SessionLocal()

    guild_id = getattr(config, "DISCORD_GUILD_ID", None) or getattr(config, "GUILD_ID", None)
    bot_token = getattr(config, "DISCORD_BOT_TOKEN", None)

    if not guild_id:
        raise RuntimeError("DISCORD_GUILD_ID / GUILD_ID 未設定")

    if not bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN 未設定")

    customer_service_role_ids = normalize_role_ids(
        getattr(config, "CUSTOMER_SERVICE_ROLE_IDS", set())
    )

    if not customer_service_role_ids:
        customer_service_role_ids = {CUSTOMER_SERVICE_ROLE_ID}

    headers = {"Authorization": f"Bot {bot_token}"}

    members = []
    after = "0"

    while True:
        response = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/members",
            headers=headers,
            params={"limit": 1000, "after": after},
            timeout=30,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Discord API 抓成員失敗：{response.status_code} {response.text[:500]}")

        batch = response.json()

        if not batch:
            break

        members.extend(batch)
        after = str(batch[-1]["user"]["id"])

        if len(batch) < 1000:
            break

    now = datetime.now()
    scanned = len(members)
    written = 0
    disabled_count = 0
    active_ids = set()
    latest_role_ids_by_member = {}
    existing_members = {
        str(member.discord_id): member
        for member in db.scalars(select(WebStaffMember)).all()
    }

    for guild_member in members:
        user = guild_member.get("user") or {}
        discord_id = str(user.get("id") or "").strip()

        if not discord_id:
            continue

        role_ids = normalize_role_ids(guild_member.get("roles", []))

        latest_role_ids_by_member[discord_id] = role_ids
        is_customer_service = bool(role_ids & customer_service_role_ids)
        is_receiver = bool(role_ids & RECEIVER_ROLE_IDS)
        is_game_receiver = bool(role_ids & GAME_ROLE_IDS)
        is_worker = bool(is_receiver or is_game_receiver)
        is_companion = bool(role_ids & COMPANION_ROLE_IDS)

        # 網頁收客服、舊服務職位，以及獨立的遊戲階級接單身分組。
        if not (is_customer_service or is_worker or is_companion):
            continue

        active_ids.add(discord_id)

        member = existing_members.get(discord_id)

        if member is None:
            member = WebStaffMember(
                discord_id=discord_id,
                created_at=now,
            )
            db.add(member)
            existing_members[discord_id] = member

        member.username = user.get("username")
        member.display_name = guild_member.get("nick") or user.get("global_name") or user.get("username")
        member.global_name = user.get("global_name")
        member.avatar = user.get("avatar")
        member.roles_json = json.dumps(sorted(role_ids), ensure_ascii=False)
        member.is_customer_service = is_customer_service
        member.is_worker = is_worker
        member.is_companion = is_companion
        member.is_active = True
        member.last_synced_at = now

        written += 1

    # Disable anyone who no longer has an eligible Discord role.
    # This also handles members who have left the Discord server.
    for discord_id, member in existing_members.items():
        if discord_id in active_ids:
            continue

        was_active = bool(
            member.is_active
            or member.is_customer_service
            or member.is_worker
            or member.is_companion
        )

        latest_role_ids = latest_role_ids_by_member.get(discord_id)

        if latest_role_ids is None:
            member.roles_json = json.dumps(
                [],
                ensure_ascii=False,
            )
        else:
            member.roles_json = json.dumps(
                sorted(latest_role_ids),
                ensure_ascii=False,
            )

        member.is_customer_service = False
        member.is_worker = False
        member.is_companion = False
        member.is_active = False
        member.last_synced_at = now

        if was_active:
            disabled_count += 1

    if owns_session:
        db.commit()
        db.close()

    return {
        "scanned": scanned,
        "written": written,
        "total_seen": scanned,
        "synced_count": written,
        "disabled_count": disabled_count,
        "message": f"成員同步完成：掃描 {scanned} 人，寫入 {written} 人。",
    }
