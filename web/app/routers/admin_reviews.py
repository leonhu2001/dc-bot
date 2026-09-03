from __future__ import annotations
from fastapi.templating import Jinja2Templates

import sqlite3

from pathlib import Path

from fastapi import (
    APIRouter,
    Request,
)

from fastapi.responses import (
    RedirectResponse,
)

from fastapi.templating import (
    Jinja2Templates,
)



# MAWAN_PORTAL_DESIGN_SYSTEM_R3 REVIEW TEMPLATE

_mw_review_templates = Jinja2Templates(
    directory=str(
        Path(__file__).resolve()
        .parents[1]
        / "templates"
    )
)


router = APIRouter(
    prefix="/admin/reviews",
    tags=["admin-reviews"],
)


TEMPLATES_DIR = (
    Path(__file__).resolve()
    .parents[1]
    / "templates"
)


templates = Jinja2Templates(
    directory=str(
        TEMPLATES_DIR
    )
)


def _db_path() -> Path:

    return (
        Path(__file__).resolve()
        .parents[3]
        / "web_dashboard.db"
    )


def _connect() -> sqlite3.Connection:

    conn = sqlite3.connect(
        _db_path(),
        timeout=15,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    return conn


def _ensure_tables() -> None:

    conn = _connect()

    try:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                customer_discord_id TEXT,
                rating INTEGER NOT NULL,
                comment TEXT,
                service_category TEXT,
                service_item TEXT,
                order_content TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_review_skips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT,
                staff_discord_id TEXT,
                skipped_all INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL
            );
            """
        )

        conn.commit()

    finally:

        conn.close()


def _require_admin(
    request: Request,
) -> dict | None:

    user = request.session.get(
        "user"
    )

    if not user:

        return None

    if not user.get(
        "is_admin"
    ):

        return None

    return user


@router.get("/")
async def review_list(
    request: Request,
    staff_id: str | None = None,
    public: str | None = None,
):

    user = _require_admin(
        request
    )

    if user is None:

        return RedirectResponse(
            url="/no-access",
            status_code=303,
        )

    _ensure_tables()

    where = []
    params = []

    if staff_id:

        where.append(
            "staff_discord_id = ?"
        )

        params.append(
            str(
                staff_id
            )
        )

    if public == "1":

        where.append(
            "is_public = 1"
        )

    elif public == "0":

        where.append(
            "is_public = 0"
        )

    where_sql = (
        "WHERE "
        + " AND ".join(
            where
        )
        if where
        else ""
    )

    conn = _connect()

    try:

        rows = conn.execute(
            f"""
            SELECT *

            FROM order_reviews

            {where_sql}

            ORDER BY
                id DESC

            LIMIT 300
            """,
            params,
        ).fetchall()

        skip_row = conn.execute(
            """
            SELECT COUNT(*) AS c

            FROM order_review_skips
            """
        ).fetchone()

        skip_count = (
            int(
                skip_row["c"]
                or 0
            )
            if skip_row
            else 0
        )

    finally:

        conn.close()

    return _mw_review_templates.TemplateResponse(
        request=request,
        name="admin_reviews.html",
        context={
            "title":
                "評價管理｜魔丸娛樂",

            "user":
                user,

            "rows":
                rows,

            "skip_count":
                skip_count,

            "staff_id":
                staff_id
                or "",

            "public":
                public
                or "",
        },
    )



@router.post(
    "/{review_id}/toggle-hidden"
)
async def toggle_hidden(
    request: Request,
    review_id: int,
):

    user = _require_admin(
        request
    )

    if user is None:

        return RedirectResponse(
            url="/no-access",
            status_code=303,
        )

    _ensure_tables()

    conn = _connect()

    try:

        conn.execute(
            """
            UPDATE order_reviews

            SET
                is_hidden =
                    CASE
                        WHEN COALESCE(
                            is_hidden,
                            0
                        ) = 1
                        THEN 0
                        ELSE 1
                    END,

                updated_at =
                    datetime('now')

            WHERE id = ?
            """,
            (
                review_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()

    return RedirectResponse(
        url="/admin/reviews/",
        status_code=303,
    )


@router.post(
    "/{review_id}/toggle-public"
)
async def toggle_public(
    request: Request,
    review_id: int,
):

    user = _require_admin(
        request
    )

    if user is None:

        return RedirectResponse(
            url="/no-access",
            status_code=303,
        )

    _ensure_tables()

    conn = _connect()

    try:

        conn.execute(
            """
            UPDATE order_reviews

            SET
                is_public =
                    CASE
                        WHEN COALESCE(
                            is_public,
                            1
                        ) = 1
                        THEN 0
                        ELSE 1
                    END,

                updated_at =
                    datetime('now')

            WHERE id = ?
            """,
            (
                review_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()

    return RedirectResponse(
        url="/admin/reviews/",
        status_code=303,
    )
