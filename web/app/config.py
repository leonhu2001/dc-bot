import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / "web" / ".env"

load_dotenv(ENV_PATH)


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

    ADMIN_ROLE_IDS = {
        role_id.strip()
        for role_id in os.getenv(
            "ADMIN_ROLE_IDS",
            "1131128849443328030,1482084782031638548",
        ).split(",")
        if role_id.strip()
    }

    WORKER_ROLE_IDS = {
        role_id.strip()
        for role_id in os.getenv(
            "WORKER_ROLE_IDS",
            "1503701170504339458,1503706721883783218",
        ).split(",")
        if role_id.strip()
    }

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'web_dashboard.db'}",
    )

    WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", "change-this-secret")


config = WebConfig()