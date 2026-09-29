from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
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

    try:
        raw_lines = path.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines()
    except OSError:
        # The web service intentionally runs as an unprivileged account and
        # should not require read access to the bot's root .env file.
        return env

    for raw in raw_lines:
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


STAFF_CARD_CACHE_DIR = Path("/tmp/mowan-staff-cards")
STAFF_CARD_MAX_BYTES = 12 * 1024 * 1024
STAFF_CARD_HOSTS = {
    "cdn.discordapp.com",
    "media.discordapp.net",
}
STAFF_CARD_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}


def _staff_card_profile(discord_id: str) -> dict:
    discord_id = str(discord_id or "").strip()
    if not discord_id or not db_path().exists():
        return {}

    try:
        with sqlite3.connect(db_path(), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            cols = table_columns(conn, "staff_profiles")
            required = {
                "staff_discord_id",
                "card_image_url",
            }
            if not required.issubset(cols):
                return {}

            select_cols = [
                "staff_discord_id",
                "card_image_url",
            ]
            for optional in (
                "forum_thread_id",
                "is_public",
            ):
                if optional in cols:
                    select_cols.append(optional)

            row = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM staff_profiles
                WHERE CAST(staff_discord_id AS TEXT) = ?
                LIMIT 1
                """,
                (discord_id,),
            ).fetchone()

            if not row:
                return {}

            data = dict(row)
            if (
                "is_public" in data
                and int(data.get("is_public") or 0) != 1
            ):
                return {}

            return data
    except Exception:
        return {}


def _trusted_staff_card_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    if (
        parsed.scheme != "https"
        or parsed.hostname not in STAFF_CARD_HOSTS
        or not str(parsed.path or "").startswith("/attachments/")
    ):
        return ""

    return url


def _staff_card_source_key(profile: dict) -> str:
    stored_url = _trusted_staff_card_url(
        str(profile.get("card_image_url") or "")
    )
    if stored_url:
        try:
            return "attachment:" + str(urlparse(stored_url).path or "")
        except Exception:
            pass

    thread_id = str(profile.get("forum_thread_id") or "").strip()
    if thread_id.isdigit():
        return f"thread:{thread_id}"

    return ""


def _staff_card_cache_paths(
    discord_id: str,
) -> tuple[Path | None, Path]:
    STAFF_CARD_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_file = STAFF_CARD_CACHE_DIR / f"{discord_id}.source"
    image_file = None

    for suffix in STAFF_CARD_SUFFIXES:
        candidate = STAFF_CARD_CACHE_DIR / f"{discord_id}{suffix}"
        if candidate.exists() and candidate.is_file():
            image_file = candidate
            break

    return image_file, source_file


def _staff_card_cached_file(
    discord_id: str,
    source_key: str,
) -> Path | None:
    try:
        image_file, source_file = _staff_card_cache_paths(discord_id)
        if image_file is None or not source_file.exists():
            return None

        cached_key = source_file.read_text(
            encoding="utf-8",
            errors="ignore",
        ).strip()

        if cached_key != source_key:
            return None

        return image_file
    except Exception:
        return None


def _attachment_is_image(attachment: dict) -> bool:
    content_type = str(attachment.get("content_type") or "").lower()
    if content_type.startswith("image/"):
        return True

    filename = str(attachment.get("filename") or "").lower()
    return any(
        filename.endswith(suffix)
        for suffix in STAFF_CARD_SUFFIXES
    )


def _discord_message_attachment_url(message: dict) -> str:
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        if not _attachment_is_image(attachment):
            continue

        for field in ("url", "proxy_url"):
            candidate = _trusted_staff_card_url(
                str(attachment.get(field) or "")
            )
            if candidate:
                return candidate

    return ""


def _discord_api_json(url: str, token: str):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "MawanWeb/1.0",
        },
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(
            resp.read().decode("utf-8")
        )


def _fresh_staff_card_url_from_thread(thread_id: str) -> str:
    thread_id = str(thread_id or "").strip()
    if not thread_id.isdigit():
        return ""

    token = get_setting(
        "DISCORD_BOT_TOKEN",
        "DISCORD_TOKEN",
        "BOT_TOKEN",
        "TOKEN",
    )
    if not token:
        return ""

    starter_url = (
        "https://discord.com/api/v10/"
        f"channels/{thread_id}/messages/{thread_id}"
    )

    try:
        starter = _discord_api_json(
            starter_url,
            token,
        )
        if isinstance(starter, dict):
            url = _discord_message_attachment_url(starter)
            if url:
                return url
    except Exception:
        pass

    history_url = (
        "https://discord.com/api/v10/"
        f"channels/{thread_id}/messages?limit=50"
    )

    try:
        messages = _discord_api_json(
            history_url,
            token,
        )
    except Exception:
        return ""

    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        url = _discord_message_attachment_url(message)
        if url:
            return url

    return ""


def _staff_card_suffix(url: str, content_type: str) -> str:
    try:
        suffix = Path(
            str(urlparse(url).path or "")
        ).suffix.lower()
    except Exception:
        suffix = ""

    if suffix in STAFF_CARD_SUFFIXES:
        return suffix

    content_type = str(content_type or "").lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return mapping.get(
        content_type.split(";", 1)[0].strip(),
        ".jpg",
    )


def _download_staff_card(
    discord_id: str,
    url: str,
    source_key: str,
) -> Path | None:
    url = _trusted_staff_card_url(url)
    if not url:
        return None

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MawanWeb/1.0",
            },
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = str(
                resp.headers.get("Content-Type")
                or ""
            ).lower()

            if not content_type.startswith("image/"):
                return None

            data = resp.read(
                STAFF_CARD_MAX_BYTES + 1
            )

        if (
            not data
            or len(data) > STAFF_CARD_MAX_BYTES
        ):
            return None

        suffix = _staff_card_suffix(
            url,
            content_type,
        )

        STAFF_CARD_CACHE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        for old_suffix in STAFF_CARD_SUFFIXES:
            old_path = (
                STAFF_CARD_CACHE_DIR
                / f"{discord_id}{old_suffix}"
            )
            if old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass

        target = (
            STAFF_CARD_CACHE_DIR
            / f"{discord_id}{suffix}"
        )
        target.write_bytes(data)

        (
            STAFF_CARD_CACHE_DIR
            / f"{discord_id}.source"
        ).write_text(
            source_key,
            encoding="utf-8",
        )

        return target
    except Exception:
        return None


def resolve_staff_card_file(
    discord_id: str,
) -> Path | None:
    discord_id = str(discord_id or "").strip()
    if not discord_id.isdigit():
        return None

    profile = _staff_card_profile(discord_id)
    if not profile:
        return None

    source_key = _staff_card_source_key(profile)
    if not source_key:
        return None

    cached = _staff_card_cached_file(
        discord_id,
        source_key,
    )
    if cached is not None:
        return cached

    stored_url = _trusted_staff_card_url(
        str(profile.get("card_image_url") or "")
    )
    if stored_url:
        downloaded = _download_staff_card(
            discord_id,
            stored_url,
            source_key,
        )
        if downloaded is not None:
            return downloaded

    thread_id = str(
        profile.get("forum_thread_id")
        or ""
    ).strip()

    fresh_url = (
        _fresh_staff_card_url_from_thread(
            thread_id
        )
        if thread_id
        else ""
    )

    if not fresh_url:
        return None

    downloaded = _download_staff_card(
        discord_id,
        fresh_url,
        source_key,
    )
    if downloaded is not None:
        try:
            with sqlite3.connect(
                db_path(),
                timeout=5,
            ) as conn:
                conn.execute(
                    """
                    UPDATE staff_profiles
                    SET card_image_url = ?
                    WHERE CAST(staff_discord_id AS TEXT) = ?
                    """,
                    (
                        fresh_url,
                        discord_id,
                    ),
                )
                conn.commit()
        except Exception:
            pass

    return downloaded


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
        known_staff = await run_in_threadpool(is_known_staff, discord_id)

        if known_staff:
            # Staff avatars follow the roster's Discord snapshot, including a
            # server-specific avatar when one exists.
            url = await run_in_threadpool(
                resolve_staff_avatar_url,
                discord_id,
                size,
            )
        else:
            url = session_avatar_url(request, discord_id, size)
            if not url:
                # Unknown IDs never trigger Discord Bot API calls.
                url = default_avatar_url(discord_id)

    response = RedirectResponse(url, status_code=302)
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@router.get("/staff-card/{discord_id}")
async def staff_card(
    discord_id: str,
):
    discord_id = str(discord_id or "").strip()

    if not discord_id.isdigit() or len(discord_id) > 25:
        return Response(status_code=404)

    path = await run_in_threadpool(
        resolve_staff_card_file,
        discord_id,
    )

    if path is None or not path.exists():
        return Response(status_code=404)

    response = FileResponse(path)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response
