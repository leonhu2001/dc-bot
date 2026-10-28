from __future__ import annotations

import json
import sqlite3
from pathlib import Path


_INSTALLED = False
_CANONICAL_BLACK_TIDE_KEYS = {
    "basic_black_tide_entertain",
    "basic_black_tide_tech",
}
_BLACK_TIDE_PREFIX = "basic_black_tide_"
_BLACK_TIDE_CATEGORY = "delta_desktop_basic"
_BLACK_TIDE_GROUP_LABEL = "黑潮爆破"


def _is_retired_black_tide_key(rule_key: str) -> bool:
    key = str(rule_key or "").strip()
    return (
        key.startswith(_BLACK_TIDE_PREFIX)
        and key not in _CANONICAL_BLACK_TIDE_KEYS
    )


def _decode_payload(value) -> dict:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _effective_custom_group_label(rule, override_item) -> str:
    payload = (override_item or {}).get("payload") or {}
    if isinstance(payload, dict) and "catalog_group_label" in payload:
        return str(payload.get("catalog_group_label") or "").strip()
    return str(getattr(rule, "catalog_group_label", "") or "").strip()


def _is_retired_black_tide_custom_rule(rule_key: str, rule, override_item) -> bool:
    """Return True for any SQLite custom rule trying to occupy Black Tide checkout.

    Older production rows are not guaranteed to use the historical
    ``basic_black_tide_*`` keys. Products created from the Web manager receive
    ``admin_delta_desktop_basic_*`` keys and can still carry
    ``catalog_group_label=黑潮爆破``. Both Discord and Web dynamically merge those
    custom rules into the catalog, so key-only filtering is insufficient.
    """
    if _is_retired_black_tide_key(rule_key):
        return True

    if rule is None:
        return False

    category = str(getattr(rule, "category", "") or "").strip()
    if category != _BLACK_TIDE_CATEGORY:
        return False

    return _effective_custom_group_label(rule, override_item) == _BLACK_TIDE_GROUP_LABEL


def retire_stale_black_tide_custom_rows(db_file: str | Path | None = None) -> int:
    """Persistently deactivate legacy Web-manager products in the Black Tide group.

    The row and its version/audit history are intentionally retained. Only
    ``custom_order_rules.is_active`` is changed, so historical orders remain
    resolvable while the stale product no longer participates in live catalogs.
    """
    from services.order_rule_store import default_db_path

    path = Path(db_file) if db_file is not None else default_db_path()
    if not path.exists():
        return 0

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        custom_table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='custom_order_rules'
            LIMIT 1
            """
        ).fetchone()
        if custom_table is None:
            return 0

        override_table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='order_rule_overrides'
            LIMIT 1
            """
        ).fetchone()

        override_payloads: dict[str, dict] = {}
        if override_table is not None:
            for row in conn.execute(
                "SELECT rule_key, payload_json FROM order_rule_overrides"
            ).fetchall():
                override_payloads[str(row["rule_key"] or "")] = _decode_payload(
                    row["payload_json"]
                )

        stale_keys: list[str] = []
        rows = conn.execute(
            """
            SELECT rule_key, category, payload_json
            FROM custom_order_rules
            WHERE is_active = 1
            """
        ).fetchall()

        for row in rows:
            key = str(row["rule_key"] or "").strip()
            category = str(row["category"] or "").strip()
            payload = _decode_payload(row["payload_json"])

            if _is_retired_black_tide_key(key):
                stale_keys.append(key)
                continue

            if category != _BLACK_TIDE_CATEGORY:
                continue

            override_payload = override_payloads.get(key) or {}
            if "catalog_group_label" in override_payload:
                group_label = str(
                    override_payload.get("catalog_group_label") or ""
                ).strip()
            else:
                group_label = str(payload.get("catalog_group_label") or "").strip()

            if group_label == _BLACK_TIDE_GROUP_LABEL:
                stale_keys.append(key)

        if stale_keys:
            conn.executemany(
                "UPDATE custom_order_rules SET is_active = 0 WHERE rule_key = ?",
                [(key,) for key in stale_keys],
            )
            conn.commit()

    return len(stale_keys)


def install_black_tide_legacy_tombstone() -> None:
    """Prevent removed Black Tide fixed-seat rules from reappearing via SQLite.

    Black Tide checkout is canonical now: the customer chooses only 娛樂陪/技術陪,
    then chooses 1-4 companions through the shared player-count selector. Historical
    custom_order_rules rows may still exist on production from older manager/runtime
    migrations. Some use old ``basic_black_tide_*`` keys while Web-created products
    use generated ``admin_*`` keys but still live under the 黑潮爆破 catalog group.

    First persistently retire matching active custom rows in SQLite. Then keep a
    read-time tombstone as a second guard so an old row or future stale override can
    never re-enter live Discord/Web catalogs. Other custom groups are untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import order_rules

    try:
        retire_stale_black_tide_custom_rows()
    except Exception:
        # Checkout must still boot if the manager database is temporarily locked or
        # unavailable. The read-time guard below remains effective in that case.
        pass

    rules = order_rules.ORDER_RULES
    if getattr(rules, "_black_tide_legacy_tombstone_installed", False):
        rules.invalidate()
        _INSTALLED = True
        return

    original_refresh = rules._refresh_external

    def _refresh_external_without_retired_black_tide() -> None:
        original_refresh()
        stale_keys = [
            key
            for key, rule in tuple(rules._custom_cache.items())
            if _is_retired_black_tide_custom_rule(
                key,
                rule,
                rules._override_cache.get(key),
            )
        ]
        for key in stale_keys:
            rules._custom_cache.pop(key, None)
            rules._override_cache.pop(key, None)

    rules._refresh_external = _refresh_external_without_retired_black_tide
    rules._black_tide_legacy_tombstone_installed = True
    rules.invalidate()
    rules._refresh_external()
    _INSTALLED = True


__all__ = [
    "install_black_tide_legacy_tombstone",
    "retire_stale_black_tide_custom_rows",
]
