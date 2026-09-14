import requests
from fastapi import HTTPException

from web.app.config import config
from web.app.services.role_catalog import (
    COMPANION_ROLE_IDS,
    PROTECTOR_ROLE_IDS,
    RECEIVER_ROLE_IDS,
    can_login_dashboard,
    is_companion as catalog_is_companion,
    is_customer_service as catalog_is_customer_service,
    is_game_receiver,
    is_protector,
    normalize_role_ids,
)

DISCORD_API_BASE = "https://discord.com/api/v10"


def _normalize_role_ids(value) -> set[str]:
    if not value:
        return set()

    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}

    return {
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    }


def has_any_allowed_web_role(roles) -> bool:
    role_set = _normalize_role_ids(roles)

    allowed_role_ids = set()
    allowed_role_ids |= _normalize_role_ids(getattr(config, "ADMIN_ROLE_IDS", set()))
    allowed_role_ids |= _normalize_role_ids(getattr(config, "CUSTOMER_SERVICE_ROLE_IDS", set()))
    allowed_role_ids |= _normalize_role_ids(getattr(config, "WORKER_ROLE_IDS", set()))
    allowed_role_ids |= _normalize_role_ids(getattr(config, "COMPANION_ROLE_IDS", set()))

    return bool(role_set & allowed_role_ids)


def fetch_guild_member(discord_user_id: str) -> dict:
    if not config.DISCORD_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="DISCORD_BOT_TOKEN is not configured")

    if not config.DISCORD_GUILD_ID:
        raise HTTPException(status_code=500, detail="DISCORD_GUILD_ID is not configured")

    response = requests.get(
        f"{DISCORD_API_BASE}/guilds/{config.DISCORD_GUILD_ID}/members/{discord_user_id}",
        headers={
            "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}",
        },
        timeout=15,
    )

    if response.status_code == 404:
        raise HTTPException(status_code=403, detail="你不在指定 Discord 伺服器內")

    if response.status_code != 200:
        # 不把 Discord 回傳 body 直接暴露給前端，避免洩漏上游細節。
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch guild member: HTTP {response.status_code}",
        )

    return response.json()


def get_member_role_ids(discord_user_id: str) -> list[str]:
    member = fetch_guild_member(discord_user_id)
    return [str(role_id) for role_id in member.get("roles", [])]


def get_dashboard_access(role_ids: list[str]) -> dict:
    roles = normalize_role_ids(role_ids)

    manager_role_ids = normalize_role_ids(getattr(config, "ADMIN_ROLE_IDS", set()))
    customer_service_role_ids = normalize_role_ids(getattr(config, "CUSTOMER_SERVICE_ROLE_IDS", set()))

    is_manager = bool(roles & manager_role_ids)
    is_customer_service = catalog_is_customer_service(roles, customer_service_role_ids)
    is_worker = is_protector(roles) or catalog_is_companion(roles) or is_game_receiver(roles)
    is_companion = catalog_is_companion(roles)
    can_access = can_login_dashboard(
        roles,
        admin_role_ids=manager_role_ids,
        customer_service_role_ids=customer_service_role_ids,
    )

    print(
        "[dashboard_access]",
        "roles=", sorted(roles),
        "manager=", is_manager,
        "cs=", is_customer_service,
        "worker=", is_worker,
        "companion=", is_companion,
        "can_access=", can_access,
    )

    return {
        "can_access": can_access,
        # is_admin 保留給舊路由作為「總管」原始旗標；session 層會另外
        # 建立相容用 is_admin = 總管或客服。
        "is_admin": is_manager,
        "is_manager": is_manager,
        "is_customer_service": is_customer_service,
        "is_worker": is_worker,
        "is_companion": is_companion,
        "role_ids": list(roles),
    }
