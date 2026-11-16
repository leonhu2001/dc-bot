from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services import order_rule_store


_STATUS_CACHE: dict[str, dict[str, Any]] = {}
_STATUS_CACHE_AT = 0.0
_STATUS_CACHE_PATH = ""
_STATUS_CACHE_SECONDS = 2.0
_WEB_GUARDS_INSTALLED = False
_DISCORD_GUARDS_INSTALLED = False


def _path(db_file: str | Path | None = None) -> Path:
    return Path(db_file) if db_file is not None else order_rule_store.default_db_path()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_order_product_status_store(db_file: str | Path | None = None) -> None:
    path = _path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_rule_product_status (
                rule_key TEXT PRIMARY KEY,
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_by_discord_id TEXT,
                updated_by_display_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_order_rule_product_status_active
            ON order_rule_product_status(is_active, rule_key);
            """
        )
        conn.commit()


def invalidate_order_product_status_cache() -> None:
    global _STATUS_CACHE, _STATUS_CACHE_AT, _STATUS_CACHE_PATH
    _STATUS_CACHE = {}
    _STATUS_CACHE_AT = 0.0
    _STATUS_CACHE_PATH = ""


def load_order_product_statuses(
    db_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = _path(db_file)
    if not path.exists():
        return {}

    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=2.0,
        )
    except sqlite3.Error:
        return {}

    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='order_rule_product_status'
            LIMIT 1
            """
        ).fetchone()
        if table is None:
            return {}

        rows = conn.execute(
            """
            SELECT
                rule_key,
                is_active,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            FROM order_rule_product_status
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    return {
        str(row["rule_key"]): {
            "rule_key": str(row["rule_key"]),
            "is_active": bool(int(row["is_active"] or 0)),
            "updated_by_discord_id": str(row["updated_by_discord_id"] or ""),
            "updated_by_display_name": str(row["updated_by_display_name"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        for row in rows
        if str(row["rule_key"] or "").strip()
    }


def _cached_statuses() -> dict[str, dict[str, Any]]:
    global _STATUS_CACHE, _STATUS_CACHE_AT, _STATUS_CACHE_PATH

    path = str(_path())
    now = time.monotonic()
    if (
        path == _STATUS_CACHE_PATH
        and now - _STATUS_CACHE_AT < _STATUS_CACHE_SECONDS
    ):
        return _STATUS_CACHE

    _STATUS_CACHE = load_order_product_statuses()
    _STATUS_CACHE_AT = now
    _STATUS_CACHE_PATH = path
    return _STATUS_CACHE


def get_order_product_status(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    if not key:
        return {"rule_key": "", "is_active": False, "updated_at": ""}

    if db_file is not None:
        item = load_order_product_statuses(db_file).get(key)
    else:
        item = _cached_statuses().get(key)

    if item is None:
        return {
            "rule_key": key,
            "is_active": True,
            "updated_by_discord_id": "",
            "updated_by_display_name": "",
            "updated_at": "",
        }
    return dict(item)


def is_order_product_active(
    rule_key: str,
    db_file: str | Path | None = None,
) -> bool:
    return bool(get_order_product_status(rule_key, db_file).get("is_active", True))


def set_order_product_active(
    *,
    rule_key: str,
    is_active: bool,
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    if not key:
        raise ValueError("缺少商品代碼。")

    path = _path(db_file)
    ensure_order_product_status_store(path)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO order_rule_product_status (
                rule_key,
                is_active,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(rule_key)
            DO UPDATE SET
                is_active = excluded.is_active,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = excluded.updated_at
            """,
            (
                key,
                1 if is_active else 0,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.commit()

    invalidate_order_product_status_cache()
    return {
        "rule_key": key,
        "is_active": bool(is_active),
        "updated_by_discord_id": str(actor_discord_id or ""),
        "updated_by_display_name": str(actor_display_name or ""),
        "updated_at": now,
    }


class StatusAwareHiddenRuleKeys(set):
    """Static hidden keys plus manager-controlled product availability."""

    def __contains__(self, value) -> bool:
        key = str(value or "").strip()
        return set.__contains__(self, value) or (
            bool(key) and not is_order_product_active(key)
        )


def install_web_catalog_guards() -> None:
    """Compatibility entrypoint: native public modules own their guards.

    Web catalog/checkout import StatusAwareHiddenRuleKeys directly, and
    categories are derived from the active catalog. Never rewrite module
    globals or functions when the admin router is imported.
    """
    global _WEB_GUARDS_INSTALLED
    _WEB_GUARDS_INSTALLED = True



def install_discord_catalog_guards() -> None:
    """Compatibility entrypoint: native catalog and submit guard are active.

    These guards are now source-owned by services.orders and
    services.self_service_runtime. In particular, NEVER assign a function
    __code__: doing so silently overwrites approved catalog/checkout logic and
    makes behavior depend on import/test order.
    """
    global _DISCORD_GUARDS_INSTALLED
    _DISCORD_GUARDS_INSTALLED = True


__all__ = [
    "StatusAwareHiddenRuleKeys",
    "ensure_order_product_status_store",
    "get_order_product_status",
    "install_discord_catalog_guards",
    "install_web_catalog_guards",
    "invalidate_order_product_status_cache",
    "is_order_product_active",
    "load_order_product_statuses",
    "set_order_product_active",
]
