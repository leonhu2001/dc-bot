from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["discord-avatars"])

DISCORD_CDN_HOST = "cdn.discordapp.com"


def db_path() -> Path:
    return Path("/opt/dc-bot/web_dashboard.db")


def default_avatar_url(discord_id: str) -> str:
    try:
        index = int(str(discord_id or "0")) % 5
    except Exception:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def _normalize_cached_discord_avatar_url(url: str, size: int) -> str:
    url = str(url or "").strip()
    if not url:
        return ""

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    if parsed.scheme != "https" or parsed.hostname != DISCORD_CDN_HOST:
        return ""

    path = str(parsed.path or "")
    trusted_prefixes = (
        "/avatars/",
        "/guilds/",
        "/embed/avatars/",
    )
    if not path.startswith(trusted_prefixes):
        return ""

    base = f"https://{DISCORD_CDN_HOST}{path}"
    if path.startswith(("/avatars/", "/guilds/")):
        return f"{base}?size={int(size or 512)}"
    return base


def avatar_cdn_url(discord_id: str, avatar_hash: str, size: int = 128) -> str:
    discord_id = str(discord_id or "").strip()
    avatar_hash = str(avatar_hash or "").strip()

    if not discord_id or not avatar_hash:
        return ""

    # Old rows may accidentally contain a URL in the avatar field. Only accept
    # an exact Discord CDN host instead of trusting arbitrary http(s) strings.
    if avatar_hash.startswith(("http://", "https://")):
        return _normalize_cached_discord_avatar_url(avatar_hash, size)

    ext = "gif" if avatar_hash.startswith("a_") else "png"
    return f"https://{DISCORD_CDN_HOST}/avatars/{discord_id}/{avatar_hash}.{ext}?size={int(size or 128)}"


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
    except Exception:
        return set()


def ensure_avatar_url_column(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "web_staff_members")
    if cols and "avatar_url" not in cols:
        conn.execute("ALTER TABLE web_staff_members ADD COLUMN avatar_url TEXT")


def is_known_staff(discord_id: str) -> bool:
    path = db_path()
    discord_id = str(discord_id or "").strip()

    if not path.exists() or not discord_id:
        return False

    try:
        with sqlite3.connect(path, timeout=5) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM web_staff_members
                WHERE CAST(discord_id AS TEXT) = ?
                LIMIT 1
                """,
                (discord_id,),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def avatar_from_staff_db(discord_id: str, size: int = 128) -> str:
    path = db_path()
    discord_id = str(discord_id or "").strip()

    if not path.exists() or not discord_id:
        return ""

    try:
        with sqlite3.connect(path, timeout=5) as conn:
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

            cached_url = ""
            if "avatar_url" in row.keys():
                cached_url = str(row["avatar_url"] or "").strip()

            trusted_cached = _normalize_cached_discord_avatar_url(
                cached_url,
                size,
            )
            if trusted_cached:
                return trusted_cached

            avatar_hash = ""
            if "avatar" in row.keys():
                avatar_hash = str(row["avatar"] or "").strip()

            if not avatar_hash:
                return ""

            url = avatar_cdn_url(
                discord_id,
                avatar_hash,
                size=size,
            )
            if not url:
                return ""

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


def guild_avatar_cdn_url(
    guild_id: str,
    discord_id: str,
    avatar_hash: str,
    size: int = 128,
) -> str:
    guild_id = str(guild_id or "").strip()
    discord_id = str(discord_id or "").strip()
    avatar_hash = str(avatar_hash or "").strip()

    if not guild_id or not discord_id or not avatar_hash:
        return ""

    ext = "gif" if avatar_hash.startswith("a_") else "png"
    return (
        f"https://{DISCORD_CDN_HOST}/guilds/{guild_id}/users/"
        f"{discord_id}/avatars/{avatar_hash}.{ext}?size={int(size or 128)}"
    )


def fetch_live_discord_avatar(discord_id: str, size: int = 128) -> str:
    """Fetch a live avatar only for a staff id already present in our DB."""
    discord_id = str(discord_id or "").strip()

    if not is_known_staff(discord_id):
        return ""

    token = get_setting(
        "DISCORD_BOT_TOKEN",
        "DISCORD_TOKEN",
        "BOT_TOKEN",
        "TOKEN",
    )
    guild_id = get_setting(
        "GUILD_ID",
        "DISCORD_GUILD_ID",
        "DISCORD_SERVER_ID",
        "SERVER_ID",
    )

    if not discord_id or not token or not guild_id:
        return ""

    try:
        req = urllib.request.Request(
            (
                "https://discord.com/api/v10/"
                f"guilds/{guild_id}/members/{discord_id}"
            ),
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "MawanWeb/1.0",
            },
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        user = data.get("user") or {}
        guild_avatar_hash = str(data.get("avatar") or "").strip()
        user_avatar_hash = str(user.get("avatar") or "").strip()

        if guild_avatar_hash:
            url = guild_avatar_cdn_url(
                guild_id,
                discord_id,
                guild_avatar_hash,
                size=size,
            )
        elif user_avatar_hash:
            url = avatar_cdn_url(
                discord_id,
                user_avatar_hash,
                size=size,
            )
        else:
            return ""

        try:
            with sqlite3.connect(db_path(), timeout=5) as conn:
                cols = table_columns(conn, "web_staff_members")
                if cols and "discord_id" in cols:
                    ensure_avatar_url_column(conn)
                    if user_avatar_hash and "avatar" in cols:
                        conn.execute(
                            """
                            UPDATE web_staff_members
                            SET avatar = ?, avatar_url = ?
                            WHERE CAST(discord_id AS TEXT) = ?
                            """,
                            (user_avatar_hash, url, discord_id),
                        )
                    else:
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


def resolve_staff_avatar_url(discord_id: str, size: int = 128) -> str:
    return (
        avatar_from_staff_db(discord_id, size=size)
        or fetch_live_discord_avatar(discord_id, size=size)
        or default_avatar_url(discord_id)
    )


def session_avatar_url(request: Request, discord_id: str, size: int) -> str:
    user = request.session.get("user") or {}
    if str(user.get("id") or "").strip() != str(discord_id or "").strip():
        return ""

    avatar_hash = str(user.get("avatar") or "").strip()
    return (
        avatar_cdn_url(discord_id, avatar_hash, size=size)
        if avatar_hash
        else default_avatar_url(discord_id)
    )


@router.get("/discord-avatar/{discord_id}")
async def discord_avatar(
    request: Request,
    discord_id: str,
    size: int = Query(default=128, ge=32, le=512),
):
    discord_id = str(discord_id or "").strip()

    # Discord snowflakes are numeric. Rejecting malformed identifiers also
    # prevents this public endpoint from becoming an arbitrary API probe.
    if not discord_id.isdigit() or len(discord_id) > 25:
        url = default_avatar_url(discord_id)
    else:
        url = session_avatar_url(request, discord_id, size)

        if not url:
            known_staff = await run_in_threadpool(is_known_staff, discord_id)
            if known_staff:
                url = await run_in_threadpool(
                    resolve_staff_avatar_url,
                    discord_id,
                    size,
                )
            else:
                # Unknown IDs never trigger Discord Bot API calls.
                url = default_avatar_url(discord_id)

    response = RedirectResponse(url, status_code=302)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
