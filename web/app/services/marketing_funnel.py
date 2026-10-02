from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MARKETING_SESSION_KEY = "marketing_session_id"
MARKETING_ATTRIBUTION_KEY = "marketing_attribution"

ALLOWED_EVENTS = {
    "page_view",
    "landing_view",
    "cta_click",
    "view_item",
    "quote",
    "checkout",
    "order_created",
    "payment_completed",
    "login_click",
}


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def ensure_marketing_tables(
    db_file: str | Path | None = None,
) -> None:
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS marketing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                customer_discord_id TEXT,
                event_name TEXT NOT NULL,
                event_key TEXT,
                path TEXT NOT NULL,
                source TEXT,
                medium TEXT,
                campaign TEXT,
                content TEXT,
                term TEXT,
                referrer TEXT,
                properties_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_marketing_events_created
            ON marketing_events(created_at);

            CREATE INDEX IF NOT EXISTS idx_marketing_events_event_created
            ON marketing_events(event_name, created_at);

            CREATE INDEX IF NOT EXISTS idx_marketing_events_session
            ON marketing_events(session_id);

            """
        )
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(marketing_events)"
            ).fetchall()
        }

        if "event_key" not in columns:
            conn.execute(
                "ALTER TABLE marketing_events ADD COLUMN event_key TEXT"
            )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_marketing_events_unique_key
            ON marketing_events(event_name, event_key)
            WHERE event_key IS NOT NULL
            """
        )

        conn.commit()


def ensure_marketing_session(session: dict[str, Any]) -> str:
    session_id = str(session.get(MARKETING_SESSION_KEY) or "").strip()

    if len(session_id) < 16:
        session_id = secrets.token_urlsafe(18)
        session[MARKETING_SESSION_KEY] = session_id

    return session_id


def _clean(value: Any, limit: int = 180) -> str:
    return str(value or "").strip()[:limit]


def _external_referrer_source(
    referrer: str | None,
) -> str:
    referrer = _clean(referrer, 500)
    if not referrer:
        return ""

    try:
        host = str(urlsplit(referrer).hostname or "").lower()
    except Exception:
        return ""

    if not host or host.endswith("mowanentertainment.com"):
        return ""

    return host[:180]


def capture_first_touch(
    session: dict[str, Any],
    *,
    query_params: Any,
    referrer: str | None,
) -> dict[str, str]:
    existing = session.get(MARKETING_ATTRIBUTION_KEY)
    if isinstance(existing, dict) and existing:
        return {
            key: _clean(existing.get(key))
            for key in (
                "source",
                "medium",
                "campaign",
                "content",
                "term",
                "referrer",
            )
        }

    source = _clean(query_params.get("utm_source"))
    medium = _clean(query_params.get("utm_medium"))
    campaign = _clean(query_params.get("utm_campaign"))
    content = _clean(query_params.get("utm_content"))
    term = _clean(query_params.get("utm_term"))
    clean_referrer = _clean(referrer, 500)

    if not source:
        if query_params.get("gclid"):
            source = "google"
            medium = medium or "cpc"
        elif query_params.get("fbclid"):
            source = "meta"
            medium = medium or "social"
        else:
            source = _external_referrer_source(clean_referrer)

    if not source:
        source = "direct"

    attribution = {
        "source": source,
        "medium": medium,
        "campaign": campaign,
        "content": content,
        "term": term,
        "referrer": clean_referrer,
    }

    session[MARKETING_ATTRIBUTION_KEY] = attribution
    return attribution


def export_marketing_session(
    session: dict[str, Any],
) -> dict[str, Any]:
    session_id = str(
        session.get(MARKETING_SESSION_KEY)
        or ""
    ).strip()

    attribution = session.get(
        MARKETING_ATTRIBUTION_KEY
    )

    result: dict[str, Any] = {}

    if len(session_id) >= 16:
        result[MARKETING_SESSION_KEY] = session_id

    if isinstance(attribution, dict) and attribution:
        result[MARKETING_ATTRIBUTION_KEY] = {
            key: _clean(
                attribution.get(key),
                500 if key == "referrer" else 180,
            )
            for key in (
                "source",
                "medium",
                "campaign",
                "content",
                "term",
                "referrer",
            )
        }

    return result


def restore_marketing_session(
    session: dict[str, Any],
    preserved: dict[str, Any] | None,
) -> None:
    if not isinstance(preserved, dict):
        return

    session_id = str(
        preserved.get(MARKETING_SESSION_KEY)
        or ""
    ).strip()

    if len(session_id) >= 16:
        session[MARKETING_SESSION_KEY] = session_id

    attribution = preserved.get(
        MARKETING_ATTRIBUTION_KEY
    )

    if isinstance(attribution, dict) and attribution:
        session[MARKETING_ATTRIBUTION_KEY] = {
            key: _clean(
                attribution.get(key),
                500 if key == "referrer" else 180,
            )
            for key in (
                "source",
                "medium",
                "campaign",
                "content",
                "term",
                "referrer",
            )
        }


def get_attribution(session: dict[str, Any]) -> dict[str, str]:
    data = session.get(MARKETING_ATTRIBUTION_KEY)
    if not isinstance(data, dict):
        data = {}

    return {
        key: _clean(data.get(key), 500 if key == "referrer" else 180)
        for key in (
            "source",
            "medium",
            "campaign",
            "content",
            "term",
            "referrer",
        )
    }


def _safe_properties(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, Any] = {}

    for key, item in list(value.items())[:20]:
        clean_key = _clean(key, 80)
        if not clean_key:
            continue

        if isinstance(item, bool) or item is None:
            result[clean_key] = item
        elif isinstance(item, (int, float)):
            result[clean_key] = item
        else:
            result[clean_key] = _clean(item, 250)

    return result


def record_marketing_event(
    *,
    session: dict[str, Any],
    event_name: str,
    path: str,
    customer_discord_id: str | int | None = None,
    properties: dict[str, Any] | None = None,
    event_key: str | None = None,
    db_file: str | Path | None = None,
) -> int:
    event_name = _clean(event_name, 80)
    if event_name not in ALLOWED_EVENTS:
        raise ValueError("unsupported marketing event")

    ensure_marketing_tables(db_file)

    session_id = ensure_marketing_session(session)
    attribution = get_attribution(session)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO marketing_events (
                session_id,
                customer_discord_id,
                event_name,
                event_key,
                path,
                source,
                medium,
                campaign,
                content,
                term,
                referrer,
                properties_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                _clean(customer_discord_id, 64) or None,
                event_name,
                _clean(event_key, 180) or None,
                _clean(path, 300) or "/",
                attribution["source"] or None,
                attribution["medium"] or None,
                attribution["campaign"] or None,
                attribution["content"] or None,
                attribution["term"] or None,
                attribution["referrer"] or None,
                json.dumps(
                    _safe_properties(properties),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def record_attributed_order_event(
    *,
    order_id: int,
    event_name: str,
    customer_discord_id: str | int | None = None,
    properties: dict[str, Any] | None = None,
    db_file: str | Path | None = None,
) -> bool:
    event_name = _clean(event_name, 80)

    if event_name not in ALLOWED_EVENTS:
        raise ValueError("unsupported marketing event")

    ensure_marketing_tables(db_file)
    path = _db_path(db_file)
    order_key = f"order:{int(order_id)}"

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        source_row = conn.execute(
            """
            SELECT *
            FROM marketing_events
            WHERE event_name = 'order_created'
              AND event_key = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (order_key,),
        ).fetchone()

        if source_row is None:
            return False

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO marketing_events (
                session_id,
                customer_discord_id,
                event_name,
                event_key,
                path,
                source,
                medium,
                campaign,
                content,
                term,
                referrer,
                properties_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(source_row["session_id"]),
                _clean(
                    customer_discord_id
                    or source_row["customer_discord_id"],
                    64,
                )
                or None,
                event_name,
                order_key,
                f"/order/{int(order_id)}",
                source_row["source"],
                source_row["medium"],
                source_row["campaign"],
                source_row["content"],
                source_row["term"],
                source_row["referrer"],
                json.dumps(
                    _safe_properties(properties),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return int(cur.rowcount or 0) > 0


def build_marketing_snapshot(
    *,
    days: int = 30,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_marketing_tables(db_file)
    days = max(1, min(int(days or 30), 365))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat(timespec="seconds")

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        event_rows = conn.execute(
            """
            SELECT event_name, COUNT(*) AS c, COUNT(DISTINCT session_id) AS sessions
            FROM marketing_events
            WHERE created_at >= ?
            GROUP BY event_name
            """,
            (cutoff,),
        ).fetchall()

        source_rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(source, ''), 'direct') AS source,
                COALESCE(NULLIF(medium, ''), '-') AS medium,
                COUNT(DISTINCT session_id) AS sessions,
                SUM(CASE WHEN event_name='order_created' THEN 1 ELSE 0 END) AS orders
            FROM marketing_events
            WHERE created_at >= ?
            GROUP BY 1, 2
            ORDER BY orders DESC, sessions DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()

        campaign_rows = conn.execute(
            """
            SELECT
                campaign,
                COUNT(DISTINCT session_id) AS sessions,
                SUM(CASE WHEN event_name='order_created' THEN 1 ELSE 0 END) AS orders
            FROM marketing_events
            WHERE created_at >= ?
              AND COALESCE(campaign, '') <> ''
            GROUP BY campaign
            ORDER BY orders DESC, sessions DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()

    event_map = {
        str(row["event_name"]): {
            "events": int(row["c"] or 0),
            "sessions": int(row["sessions"] or 0),
        }
        for row in event_rows
    }

    funnel = []
    for name, label in (
        ("landing_view", "Landing 瀏覽"),
        ("view_item", "商品互動"),
        ("quote", "取得價格"),
        ("checkout", "進入 Checkout"),
        ("order_created", "成功建單"),
        ("payment_completed", "完成付款"),
    ):
        data = event_map.get(name, {"events": 0, "sessions": 0})
        funnel.append(
            {
                "event_name": name,
                "label": label,
                "events": int(data["events"]),
                "sessions": int(data["sessions"]),
            }
        )

    return {
        "days": days,
        "event_map": event_map,
        "funnel": funnel,
        "sources": [dict(row) for row in source_rows],
        "campaigns": [dict(row) for row in campaign_rows],
    }
