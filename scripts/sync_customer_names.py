from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app.config import config  # noqa: E402

DISCORD_API_BASE = "https://discord.com/api/v10"
WEB_DB_PATH = Path("/opt/dc-bot/web_dashboard.db") if Path("/opt/dc-bot/web_dashboard.db").exists() else PROJECT_ROOT / "web_dashboard.db"


def get_member_display_name(discord_id: str) -> str | None:
    if not config.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")

    if not config.DISCORD_GUILD_ID:
        raise RuntimeError("DISCORD_GUILD_ID is not configured")

    response = requests.get(
        f"{DISCORD_API_BASE}/guilds/{config.DISCORD_GUILD_ID}/members/{discord_id}",
        headers={"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"},
        timeout=20,
    )

    if response.status_code == 404:
        return None

    if response.status_code == 429:
        retry_after = float(response.json().get("retry_after", 1))
        time.sleep(retry_after)
        return get_member_display_name(discord_id)

    if response.status_code != 200:
        print(f"skip {discord_id}: Discord API {response.status_code} {response.text[:120]}")
        return None

    data: dict[str, Any] = response.json()
    user: dict[str, Any] = data.get("user") or {}

    return str(
        data.get("nick")
        or user.get("global_name")
        or user.get("username")
        or discord_id
    )


def should_update_name(current_name: str | None, discord_id: str) -> bool:
    if not current_name:
        return True

    normalized = str(current_name).strip()

    if not normalized:
        return True

    return normalized == str(discord_id)


def main() -> None:
    conn = sqlite3.connect(str(WEB_DB_PATH))

    rows = conn.execute(
        """
        SELECT DISTINCT customer_discord_id, customer_display_name
        FROM web_orders
        WHERE customer_discord_id IS NOT NULL
          AND TRIM(customer_discord_id) != ''
        ORDER BY customer_discord_id
        """
    ).fetchall()

    checked = 0
    updated = 0
    skipped = 0

    for customer_discord_id, customer_display_name in rows:
        checked += 1
        discord_id = str(customer_discord_id).strip()

        if not should_update_name(customer_display_name, discord_id):
            skipped += 1
            continue

        display_name = get_member_display_name(discord_id)

        if not display_name:
            skipped += 1
            continue

        conn.execute(
            """
            UPDATE web_orders
            SET customer_display_name = ?
            WHERE customer_discord_id = ?
              AND (
                  customer_display_name IS NULL
                  OR TRIM(customer_display_name) = ''
                  OR customer_display_name = customer_discord_id
              )
            """,
            (display_name, discord_id),
        )

        changed = conn.total_changes
        updated += 1
        print(f"updated customer {discord_id} -> {display_name}")

    conn.commit()

    print("")
    print(f"web_db={WEB_DB_PATH}")
    print(f"checked_customers={checked}")
    print(f"updated_customers={updated}")
    print(f"skipped_customers={skipped}")

    print("")
    print("recent_orders:")
    for row in conn.execute(
        """
        SELECT id, bot_order_no, customer_discord_id, customer_display_name, status
        FROM web_orders
        ORDER BY id DESC
        LIMIT 10
        """
    ):
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
