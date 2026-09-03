import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / "web" / ".env"

load_dotenv(ENV_PATH)


def _parse_role_ids(env_name: str, default_value: str) -> set[str]:
    return {
        role_id.strip()
        for role_id in os.getenv(env_name, default_value).split(",")
        if role_id.strip()
    }


class WebConfig:
    BASE_DIR = BASE_DIR

    DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
    DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
    DISCORD_REDIRECT_URI = os.getenv(
        "DISCORD_REDIRECT_URI",
        "http://127.0.0.1:8000/auth/discord/callback",
    )
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
    DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

    ADMIN_ROLE_IDS = _parse_role_ids(
        "ADMIN_ROLE_IDS",
        "1482084782031638548",
    )

    CUSTOMER_SERVICE_ROLE_IDS = _parse_role_ids(
        "CUSTOMER_SERVICE_ROLE_IDS",
        "1482084782031638548",
    )

    WORKER_ROLE_IDS = _parse_role_ids(
        "WORKER_ROLE_IDS",
        "1500234130871550004,1500234170943934544,1500751039060643990,1500751059239440575,1482080315798192210",
    )

    COMPANION_ROLE_IDS = _parse_role_ids(
        "COMPANION_ROLE_IDS",
        "1500751059239440575,1482080315798192210",
    )

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'web_dashboard.db'}",
    )

    WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", "")

    if not WEB_SECRET_KEY or WEB_SECRET_KEY == "change-this-secret":
        raise RuntimeError("WEB_SECRET_KEY 未設定或仍為預設值，請在 web/.env 設定正式密鑰")

    WEB_COOKIE_HTTPS_ONLY = os.getenv(
        "WEB_COOKIE_HTTPS_ONLY",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}


config = WebConfig()
