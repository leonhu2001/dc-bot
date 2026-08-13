from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["discord-avatars"])


def db_path() -> Path:
    return Path("/opt/dc-bot/web_dashboard.db")


def default_avatar_url(discord_id: str) -> str:
    try:
        index = int(str(discord_id or "0")) % 5
    except Exception:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def avatar_cdn_url(discord_id: str, avatar_hash: str, size: int = 128) -> str:
    discord_id = str(discord_id or "").strip()
    avatar_hash = str(avatar_hash or "").strip()

    if not discord_id or not avatar_hash:
        return ""

    if avatar_hash.startswith("http://") or avatar_hash.startswith("https://"):
        return avatar_hash

    ext = "gif" if avatar_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}?size={int(size or 128)}"


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def ensure_avatar_url_column(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "web_staff_members")
    if cols and "avatar_url" not in cols:
        conn.execute("ALTER TABLE web_staff_members ADD COLUMN avatar_url TEXT")


def avatar_from_staff_db(discord_id: str, size: int = 128) -> str:
    path = db_path()
    discord_id = str(discord_id or "").strip()

    if not path.exists() or not discord_id:
        return ""

    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            cols = table_columns(conn, "web_staff_members")

            if not cols or "discord_id" not in cols:
                return ""

            select_cols = ["discord_id"]
            if "avatar_url" in cols:
                select_cols.append("avatar_url")
            if "avatar" in cols:
                select_cols.append("avatar")

            row = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM web_staff_members
                WHERE CAST(discord_id AS TEXT) = ?
                LIMIT 1
                """,
                (discord_id,),
            ).fetchone()

            if not row:
                return ""

            if "avatar_url" in row.keys():
                avatar_url = str(row["avatar_url"] or "").strip()
                if avatar_url:
                    return avatar_url

            if "avatar" in row.keys():
                avatar_hash = str(row["avatar"] or "").strip()
                url = avatar_cdn_url(discord_id, avatar_hash, size=size)
                if url:
                    try:
                        ensure_avatar_url_column(conn)
                        conn.execute(
                            """
                            UPDATE web_staff_members
                            SET avatar_url = ?
                            WHERE CAST(discord_id AS TEXT) = ?
                            """,
                            (url, discord_id),
                        )
                        conn.commit()
                    except Exception:
                        pass
                    return url

    except Exception:
        return ""

    return ""


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


def fetch_live_discord_avatar(discord_id: str, size: int = 128) -> str:
    discord_id = str(discord_id or "").strip()

    token = get_setting("DISCORD_BOT_TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "TOKEN")
    guild_id = get_setting("GUILD_ID", "DISCORD_GUILD_ID", "DISCORD_SERVER_ID", "SERVER_ID")

    if not discord_id or not token or not guild_id:
        return ""

    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_id}",
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "Mozilla/5.0",
            },
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        user = data.get("user") or {}
        avatar_hash = str(user.get("avatar") or "").strip()

        if not avatar_hash:
            return ""

        url = avatar_cdn_url(discord_id, avatar_hash, size=size)

        try:
            with sqlite3.connect(db_path()) as conn:
                cols = table_columns(conn, "web_staff_members")
                if cols and "discord_id" in cols:
                    ensure_avatar_url_column(conn)
                    conn.execute(
                        """
                        UPDATE web_staff_members
                        SET avatar = COALESCE(NULLIF(avatar, ''), ?),
                            avatar_url = ?
                        WHERE CAST(discord_id AS TEXT) = ?
                        """,
                        (avatar_hash, url, discord_id),
                    )
                    conn.commit()
        except Exception:
            pass

        return url

    except Exception:
        return ""


def resolve_avatar_url(discord_id: str, size: int = 128) -> str:
    return (
        avatar_from_staff_db(discord_id, size=size)
        or fetch_live_discord_avatar(discord_id, size=size)
        or default_avatar_url(discord_id)
    )


@router.get("/discord-avatar/{discord_id}")
async def discord_avatar(discord_id: str, size: int = Query(default=128, ge=32, le=512)):
    return RedirectResponse(resolve_avatar_url(discord_id, size=size), status_code=302)
