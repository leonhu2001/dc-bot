import requests
from fastapi import HTTPException

from web.app.config import config

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
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch guild member: {response.text}",
        )

    return response.json()


def get_member_role_ids(discord_user_id: str) -> list[str]:
    member = fetch_guild_member(discord_user_id)
    return [str(role_id) for role_id in member.get("roles", [])]


def get_dashboard_access(role_ids: list[str]) -> dict:
    roles = _normalize_role_ids(role_ids)

    # 固定保險：新的打手 / 陪玩身分組，避免 config 或 env 沒吃到時登入被擋。
    fallback_worker_role_ids = _normalize_role_ids({
        "1500234130871550004",
        "1500234170943934544",
        "1500751039060643990",
    })
    fallback_companion_role_ids = _normalize_role_ids({
        "1500751059239440575",
        "1482080315798192210",
    })

    admin_role_ids = _normalize_role_ids(getattr(config, "ADMIN_ROLE_IDS", set()))
    customer_service_role_ids = _normalize_role_ids(getattr(config, "CUSTOMER_SERVICE_ROLE_IDS", set()))
    worker_role_ids = _normalize_role_ids(getattr(config, "WORKER_ROLE_IDS", set())) | fallback_worker_role_ids

    companion_role_ids = fallback_companion_role_ids

    if hasattr(config, "COMPANION_ROLE_IDS"):
        companion_role_ids |= _normalize_role_ids(config.COMPANION_ROLE_IDS)
    elif hasattr(config, "COMPANION_ROLE_ID") and config.COMPANION_ROLE_ID:
        companion_role_ids |= _normalize_role_ids({config.COMPANION_ROLE_ID})

    is_admin = bool(roles & admin_role_ids)
    is_customer_service = bool(roles & customer_service_role_ids)
    is_worker = bool(roles & worker_role_ids)
    is_companion = bool(roles & companion_role_ids)
    can_access = is_admin or is_customer_service or is_worker or is_companion

    print(
        "[dashboard_access]",
        "roles=", sorted(roles),
        "worker_ids=", sorted(worker_role_ids),
        "companion_ids=", sorted(companion_role_ids),
        "admin=", is_admin,
        "cs=", is_customer_service,
        "worker=", is_worker,
        "companion=", is_companion,
        "can_access=", can_access,
    )

    return {
        "can_access": can_access,
        "is_admin": is_admin,
        "is_customer_service": is_customer_service,
        "is_worker": is_worker,
        "is_companion": is_companion,
        "role_ids": list(roles),
    }
