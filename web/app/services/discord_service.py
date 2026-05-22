import requests
from fastapi import HTTPException

from web.app.config import config

DISCORD_API_BASE = "https://discord.com/api/v10"


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
    roles = {str(role_id) for role_id in role_ids}

    is_admin = bool(roles & config.ADMIN_ROLE_IDS)
    is_worker = bool(roles & config.WORKER_ROLE_IDS)

    return {
        "is_admin": is_admin,
        "is_worker": is_worker,
        "role_ids": list(roles),
    }