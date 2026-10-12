from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_admin(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin", status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user or not user.get("is_admin"):
        return None

    return user


def dedupe_admin_worker_members(members):
    """Return active worker/companion choices once per Discord member."""
    result = {}
    for member in members or []:
        if isinstance(member, dict):
            discord_id = str(member.get("discord_id") or "").strip()
            is_worker = bool(member.get("is_worker"))
            is_companion = bool(member.get("is_companion"))
        else:
            discord_id = str(getattr(member, "discord_id", "") or "").strip()
            is_worker = bool(getattr(member, "is_worker", False))
            is_companion = bool(getattr(member, "is_companion", False))

        if not discord_id or not (is_worker or is_companion):
            continue
        result[discord_id] = member

    def member_name(member):
        if isinstance(member, dict):
            return str(
                member.get("display_name")
                or member.get("username")
                or member.get("discord_id")
                or ""
            )
        return str(
            getattr(member, "display_name", "")
            or getattr(member, "username", "")
            or getattr(member, "discord_id", "")
        )

    return sorted(result.values(), key=member_name)


def list_admin_worker_dropdown_members() -> list[dict]:
    """Load active worker/companion choices for admin order assignment UI."""
    db_path = Path(__file__).resolve().parents[3] / "web_dashboard.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                discord_id,
                username,
                display_name,
                global_name,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            FROM web_staff_members
            WHERE COALESCE(is_active, 1) = 1
              AND (
                    COALESCE(is_worker, 0) = 1
                 OR COALESCE(is_companion, 0) = 1
              )
            ORDER BY
                COALESCE(display_name, ''),
                COALESCE(global_name, ''),
                COALESCE(username, ''),
                discord_id
            """
        ).fetchall()

        members = []
        seen = set()
        for row in rows:
            discord_id = str(row["discord_id"] or "").strip()
            if not discord_id or discord_id in seen:
                continue
            seen.add(discord_id)
            members.append(
                {
                    "discord_id": discord_id,
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "global_name": row["global_name"],
                    "is_worker": bool(row["is_worker"]),
                    "is_companion": bool(row["is_companion"]),
                    "is_customer_service": bool(row["is_customer_service"]),
                    "is_active": bool(row["is_active"]),
                }
            )
        return members
    finally:
        conn.close()
