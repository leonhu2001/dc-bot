from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SWEET_COMPANION_ROLE_KEY = "sweet_companion"

# These built-in products have a dedicated companion-count control. Their headcount
# structure is system-owned and must never be reverted by an old manager override or
# by rolling back to a pre-migration version.
_COUNT_RULE_REQUIRED_GAME_ROLE = {
    "basic_tech_secret_single": "delta_desktop",
    "basic_tech_topsecret_single": "delta_desktop",
    "basic_mobile_tech_secret_single": "delta_mobile",
    "basic_mobile_tech_topsecret_single": "delta_mobile",
    "basic_entertain_single": "delta_desktop",
    "basic_entertain_female_single": "delta_desktop",
    "basic_entertain_male_single": "delta_desktop",
    "basic_mobile_entertain_single": "delta_mobile",
    "basic_mobile_entertain_female_single": "delta_mobile",
    "basic_mobile_entertain_male_single": "delta_mobile",
}

_SWEET_CANONICAL_REQUIRED_GAME_ROLE = {
    "delta_desktop": "delta_desktop",
    "delta_mobile": "delta_mobile",
    "steam": "steam_game",
    "valorant": "valorant_game",
    "lol": "lol_game",
    "apex": "apex_game",
}

for _prefix, _game_role in _SWEET_CANONICAL_REQUIRED_GAME_ROLE.items():
    for _mode in ("female", "male", "any"):
        _COUNT_RULE_REQUIRED_GAME_ROLE[f"{_prefix}_sweet_{_mode}"] = _game_role

_SWEET_CANONICAL_KEYS = {
    f"{prefix}_sweet_{mode}"
    for prefix in _SWEET_CANONICAL_REQUIRED_GAME_ROLE
    for mode in ("female", "male", "any")
}


def normalize_builtin_rule_override_payload(
    rule_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply non-editable structural invariants before a built-in rule is stored.

    Price, service roles, benefit switches and normal manager-editable fields remain
    untouched. Only fields that define the new companion-count contract are forced.
    This happens at persistence time, so later reads do not need a monkey-patch or an
    EffectiveOrderRules wrapper to repair stale data.
    """
    key = str(rule_key or "").strip()
    result = dict(payload or {})
    game_role = _COUNT_RULE_REQUIRED_GAME_ROLE.get(key)
    if game_role is None:
        return result

    result.update({
        "required_staff_count": "player_count",
        "player_count_enabled": True,
        "min_player_count": 1,
        "max_player_count": 2,
        "price_multiply_player_count": False,
        "max_specified_count": 2,
        # The built-in catalog owns the second/third-field wording for these rules.
        # A stale manager group override would otherwise make the UI fall back to the
        # old rule label such as 「機密｜單陪」.
        "catalog_group_label": "",
    })

    if key in _SWEET_CANONICAL_KEYS:
        result["required_game_roles"] = [game_role, SWEET_COMPANION_ROLE_KEY]
    else:
        result["required_game_roles"] = [game_role]

    return result


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _path(db_file: str | Path | None = None) -> Path:
    return Path(db_file) if db_file is not None else default_db_path()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_order_rule_store(db_file: str | Path | None = None) -> None:
    path = _path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_rule_overrides (
                rule_key TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_by_discord_id TEXT,
                updated_by_display_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_rule_override_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT,
                source_version INTEGER,
                actor_discord_id TEXT,
                actor_display_name TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(rule_key, version)
            );

            CREATE INDEX IF NOT EXISTS idx_order_rule_override_versions_rule
            ON order_rule_override_versions(rule_key, version DESC);

            CREATE TABLE IF NOT EXISTS custom_order_rules (
                rule_key TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_by_discord_id TEXT,
                created_by_display_name TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_custom_order_rules_category
            ON custom_order_rules(category, is_active);
            """
        )
        conn.commit()


def _decode_payload(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_active_overrides(
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
            WHERE type='table' AND name='order_rule_overrides'
            LIMIT 1
            """
        ).fetchone()
        if table is None:
            return {}

        rows = conn.execute(
            """
            SELECT
                rule_key,
                version,
                payload_json,
                updated_by_discord_id,
                updated_by_display_name,
                updated_at
            FROM order_rule_overrides
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["rule_key"] or "").strip()
        if not key:
            continue
        result[key] = {
            "version": int(row["version"] or 0),
            "payload": _decode_payload(row["payload_json"]),
            "updated_by_discord_id": str(row["updated_by_discord_id"] or ""),
            "updated_by_display_name": str(row["updated_by_display_name"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
    return result


def get_active_override(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    return load_active_overrides(db_file).get(str(rule_key))


def load_custom_rule_definitions(
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
            WHERE type='table' AND name='custom_order_rules'
            LIMIT 1
            """
        ).fetchone()
        if table is None:
            return {}

        rows = conn.execute(
            """
            SELECT
                rule_key,
                category,
                payload_json,
                created_by_discord_id,
                created_by_display_name,
                created_at
            FROM custom_order_rules
            WHERE is_active = 1
            ORDER BY created_at ASC, rule_key ASC
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["rule_key"] or "").strip()
        category = str(row["category"] or "").strip()
        payload = _decode_payload(row["payload_json"])
        if not key or not category or not payload:
            continue
        result[key] = {
            "rule_key": key,
            "category": category,
            "payload": payload,
            "created_by_discord_id": str(row["created_by_discord_id"] or ""),
            "created_by_display_name": str(row["created_by_display_name"] or ""),
            "created_at": str(row["created_at"] or ""),
        }
    return result


def get_custom_rule_definition(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    return load_custom_rule_definitions(db_file).get(str(rule_key))


def _next_version(conn: sqlite3.Connection, rule_key: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version), 0)
        FROM order_rule_override_versions
        WHERE rule_key = ?
        """,
        (str(rule_key),),
    ).fetchone()
    return int((row[0] if row else 0) or 0) + 1


def create_custom_order_rule(
    *,
    rule_key: str,
    category: str,
    payload: dict[str, Any],
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    category_value = str(category or "").strip()
    if not key:
        raise ValueError("缺少商品代碼。")
    if not category_value:
        raise ValueError("缺少商品分類。")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("商品內容不能為空。")

    path = _path(db_file)
    ensure_order_rule_store(path)
    now = _now_iso()
    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT 1 FROM custom_order_rules WHERE rule_key = ? LIMIT 1
            """,
            (key,),
        ).fetchone()
        if existing is not None:
            raise ValueError("這個商品代碼已存在，請重新建立。")

        conn.execute(
            """
            INSERT INTO custom_order_rules (
                rule_key, category, payload_json,
                created_by_discord_id, created_by_display_name,
                created_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                key,
                category_value,
                payload_json,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )

        version = _next_version(conn, key)
        conn.execute(
            """
            INSERT INTO order_rule_override_versions (
                rule_key, version, action, payload_json, source_version,
                actor_discord_id, actor_display_name, created_at
            ) VALUES (?, ?, 'create', ?, NULL, ?, ?, ?)
            """,
            (
                key,
                version,
                payload_json,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.commit()

    return {
        "rule_key": key,
        "category": category_value,
        "payload": dict(payload),
        "version": version,
        "action": "create",
        "created_at": now,
    }


def list_rule_versions(
    rule_key: str,
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = _path(db_file)
    ensure_order_rule_store(path)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id, rule_key, version, action, payload_json, source_version,
                actor_discord_id, actor_display_name, created_at
            FROM order_rule_override_versions
            WHERE rule_key = ?
            ORDER BY version DESC
            LIMIT ?
            """,
            (str(rule_key), max(1, min(int(limit or 20), 100))),
        ).fetchall()

    return [
        {**dict(row), "payload": _decode_payload(row["payload_json"])}
        for row in rows
    ]


def publish_rule_override(
    *,
    rule_key: str,
    payload: dict[str, Any],
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    action: str = "publish",
    source_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    if not key:
        raise ValueError("缺少規則 key。")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("規則內容不能為空。")

    # Structural migrations are enforced here, at the write boundary. This makes
    # admin saves and rollbacks safe and means production reads consume already-
    # canonical data instead of repairing it with runtime overlays.
    stored_payload = normalize_builtin_rule_override_payload(key, payload)

    path = _path(db_file)
    ensure_order_rule_store(path)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT version FROM order_rule_overrides WHERE rule_key = ?",
            (key,),
        ).fetchone()
        active_version = int(active["version"] or 0) if active else 0

        if (
            expected_active_version is not None
            and int(expected_active_version) != active_version
        ):
            raise ValueError("這個商品規則已被其他人更新，請重新整理後再發布。")

        version = _next_version(conn, key)
        payload_json = json.dumps(
            stored_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        conn.execute(
            """
            INSERT INTO order_rule_override_versions (
                rule_key, version, action, payload_json, source_version,
                actor_discord_id, actor_display_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                version,
                str(action or "publish"),
                payload_json,
                int(source_version) if source_version is not None else None,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO order_rule_overrides (
                rule_key, version, payload_json,
                updated_by_discord_id, updated_by_display_name, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_key) DO UPDATE SET
                version = excluded.version,
                payload_json = excluded.payload_json,
                updated_by_discord_id = excluded.updated_by_discord_id,
                updated_by_display_name = excluded.updated_by_display_name,
                updated_at = excluded.updated_at
            """,
            (
                key,
                version,
                payload_json,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.commit()

    return {
        "rule_key": key,
        "version": version,
        "payload": dict(stored_payload),
        "action": str(action or "publish"),
        "source_version": source_version,
        "updated_at": now,
    }


def rollback_rule_override(
    *,
    rule_key: str,
    target_version: int,
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    path = _path(db_file)
    ensure_order_rule_store(path)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT payload_json
            FROM order_rule_override_versions
            WHERE rule_key = ? AND version = ? AND payload_json IS NOT NULL
            LIMIT 1
            """,
            (key, int(target_version)),
        ).fetchone()

    if row is None:
        raise ValueError("找不到可回復的規則版本。")
    payload = _decode_payload(row["payload_json"])
    if not payload:
        raise ValueError("該版本沒有可發布的規則內容。")

    return publish_rule_override(
        rule_key=key,
        payload=payload,
        actor_discord_id=actor_discord_id,
        actor_display_name=actor_display_name,
        expected_active_version=expected_active_version,
        action="rollback",
        source_version=int(target_version),
        db_file=path,
    )


def reset_rule_override(
    *,
    rule_key: str,
    actor_discord_id: str | int | None,
    actor_display_name: str | None,
    expected_active_version: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    key = str(rule_key or "").strip()
    path = _path(db_file)
    ensure_order_rule_store(path)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT version FROM order_rule_overrides WHERE rule_key = ?",
            (key,),
        ).fetchone()
        active_version = int(active["version"] or 0) if active else 0

        if active is None:
            raise ValueError("這個商品目前沒有後台覆寫，不需要重設。")
        if (
            expected_active_version is not None
            and int(expected_active_version) != active_version
        ):
            raise ValueError("這個商品規則已被其他人更新，請重新整理後再重設。")

        version = _next_version(conn, key)
        conn.execute(
            """
            INSERT INTO order_rule_override_versions (
                rule_key, version, action, payload_json, source_version,
                actor_discord_id, actor_display_name, created_at
            ) VALUES (?, ?, 'reset', NULL, ?, ?, ?, ?)
            """,
            (
                key,
                version,
                active_version,
                str(actor_discord_id or ""),
                str(actor_display_name or ""),
                now,
            ),
        )
        conn.execute("DELETE FROM order_rule_overrides WHERE rule_key = ?", (key,))
        conn.commit()

    return {
        "rule_key": key,
        "version": version,
        "action": "reset",
        "source_version": active_version,
        "updated_at": now,
    }
