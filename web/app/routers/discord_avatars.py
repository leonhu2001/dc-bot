from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["discord-avatars"])


def read_env_file() -> dict[str, str]:
    env = {}
    path = Path("/opt/dc-bot/.env")

    if not path.exists():
        return env

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

    return env


def get_setting(*names: str) -> str:
    env_file = read_env_file()

    for name in names:
        value = os.environ.get(name) or env_file.get(name)
        if value:
            return str(value).strip()

    try:
        from web.app.config import config

        for name in names:
            value = getattr(config, name, None)
            if value:
                return str(value).strip()
    except Exception:
        pass

    return ""


def db_path() -> Path:
    return Path("/opt/dc-bot/web_dashboard.db")


def default_avatar_url(discord_id: str, size: int = 128) -> str:
    try:
        index = int(str(discord_id or "0")) % 5
    except Exception:
        index = 0

    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def ensure_avatar_column() -> None:
    path = db_path()

    if not path.exists():
        return

    try:
        with sqlite3.connect(path) as conn:
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(web_staff_members)").fetchall()
            }

            if "avatar_url" not in cols:
                conn.execute("ALTER TABLE web_staff_members ADD COLUMN avatar_url TEXT")

            conn.commit()
    except Exception:
        return


def avatar_from_db(discord_id: str) -> str:
    path = db_path()

    if not path.exists():
        return ""

    try:
        ensure_avatar_column()

        with sqlite3.connect(path) as conn:
            row = conn.execute(
                """
                SELECT avatar_url
                FROM web_staff_members
                WHERE CAST(discord_id AS TEXT) = ?
                LIMIT 1
                """,
                (str(discord_id),),
            ).fetchone()

            if row and row[0]:
                return str(row[0]).strip()
    except Exception:
        return ""

    return ""


def save_avatar_to_db(discord_id: str, avatar_url: str) -> None:
    if not avatar_url:
        return

    path = db_path()

    if not path.exists():
        return

    try:
        ensure_avatar_column()

        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                UPDATE web_staff_members
                SET avatar_url = ?
                WHERE CAST(discord_id AS TEXT) = ?
                """,
                (avatar_url, str(discord_id)),
            )
            conn.commit()
    except Exception:
        return


def fetch_discord_avatar(discord_id: str, size: int = 128) -> str:
    discord_id = str(discord_id or "").strip()

    if not discord_id:
        return default_avatar_url(discord_id, size)

    cached = avatar_from_db(discord_id)

    if cached:
        return cached

    token = get_setting("DISCORD_TOKEN", "BOT_TOKEN", "TOKEN")
    guild_id = get_setting("GUILD_ID", "DISCORD_GUILD_ID", "DISCORD_SERVER_ID", "SERVER_ID")

    if not token or not guild_id:
        return default_avatar_url(discord_id, size)

    try:
        url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_id}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "Mozilla/5.0",
            },
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        user = data.get("user") or {}
        guild_avatar = data.get("avatar")
        user_avatar = user.get("avatar")

        if guild_avatar:
            avatar_url = (
                f"https://cdn.discordapp.com/guilds/{guild_id}/users/"
                f"{discord_id}/avatars/{guild_avatar}.png?size={size}"
            )
        elif user_avatar:
            ext = "gif" if str(user_avatar).startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{user_avatar}.{ext}?size={size}"
        else:
            avatar_url = default_avatar_url(discord_id, size)

        save_avatar_to_db(discord_id, avatar_url)
        return avatar_url

    except Exception:
        return default_avatar_url(discord_id, size)


@router.get("/discord-avatar/{discord_id}")
async def discord_avatar(discord_id: str, size: int = Query(default=128, ge=32, le=512)):
    return RedirectResponse(fetch_discord_avatar(discord_id, size=size), status_code=302)
