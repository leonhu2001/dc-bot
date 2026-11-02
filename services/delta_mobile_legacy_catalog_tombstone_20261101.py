from __future__ import annotations

import json
import sqlite3
from pathlib import Path


_INSTALLED = False
_MOBILE_CATEGORY = "delta_mobile_basic"
_RETIRED_RULE_KEYS = frozenset({
    "basic_mobile_tech_secret_single",
    "basic_mobile_tech_secret_double",
    "basic_mobile_tech_topsecret_single",
    "basic_mobile_tech_topsecret_double",
    "basic_mobile_one_companion_one_guard_secret",
    "basic_mobile_one_companion_one_guard_topsecret",
})
_RETIRED_GROUP_LABELS = frozenset({
    "技術陪",
    "一陪一護",
    "絕巴技術陪",
})


def _decode_payload(value) -> dict:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _effective_group_label(rule, override_item) -> str:
    payload = (override_item or {}).get("payload") or {}
    if isinstance(payload, dict) and "catalog_group_label" in payload:
        return str(payload.get("catalog_group_label") or "").strip()
    return str(getattr(rule, "catalog_group_label", "") or "").strip()


def _is_retired_mobile_custom_rule(rule, override_item=None) -> bool:
    if rule is None:
        return False
    if str(getattr(rule, "category", "") or "").strip() != _MOBILE_CATEGORY:
        return False

    key = str(getattr(rule, "key", "") or "").strip()
    if key in _RETIRED_RULE_KEYS:
        return True

    group_label = _effective_group_label(rule, override_item)
    if group_label in _RETIRED_GROUP_LABELS:
        return True

    # Very old manager rows may have no catalog_group_label and only carry their
    # display name. Keep the match intentionally narrow to retired hourly products.
    label = str(getattr(rule, "label", "") or "").strip()
    return (
        "絕巴技術陪" in label
        or "技術陪〈手遊〉" in label
        or "手遊｜技術陪" in label
        or "一陪一護〈手遊〉" in label
        or "手遊｜一陪一護" in label
    )


def retire_stale_delta_mobile_custom_rows(
    db_file: str | Path | None = None,
) -> int:
    """Deactivate retired products and remove their active overrides.

    Audit/version tables and historical order rows are intentionally retained.
    """
    from services.order_rule_store import default_db_path

    path = Path(db_file) if db_file is not None else default_db_path()
    if not path.exists():
        return 0

    changed = 0
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
        if custom_table is not None:
            rows = conn.execute(
                """
                SELECT rule_key, category, payload_json
                FROM custom_order_rules
                WHERE is_active = 1
                """
            ).fetchall()

            for row in rows:
                if str(row["category"] or "").strip() != _MOBILE_CATEGORY:
                    continue

                key = str(row["rule_key"] or "").strip()
                payload = _decode_payload(row["payload_json"])
                override_payload = override_payloads.get(key) or {}

                if "catalog_group_label" in override_payload:
                    group_label = str(
                        override_payload.get("catalog_group_label") or ""
                    ).strip()
                else:
                    group_label = str(payload.get("catalog_group_label") or "").strip()

                label = str(
                    override_payload.get("label")
                    if "label" in override_payload
                    else payload.get("label")
                    or ""
                ).strip()

                retired = key in _RETIRED_RULE_KEYS or group_label in _RETIRED_GROUP_LABELS
                if not retired and not group_label:
                    retired = (
                        "絕巴技術陪" in label
                        or "技術陪〈手遊〉" in label
                        or "手遊｜技術陪" in label
                        or "一陪一護〈手遊〉" in label
                        or "手遊｜一陪一護" in label
                    )

                if retired:
                    stale_keys.append(key)

            if stale_keys:
                conn.executemany(
                    "UPDATE custom_order_rules SET is_active = 0 WHERE rule_key = ?",
                    [(key,) for key in stale_keys],
                )
                changed += len(stale_keys)

        if override_table is not None:
            override_keys = sorted(_RETIRED_RULE_KEYS | set(stale_keys))
            for key in override_keys:
                cursor = conn.execute(
                    "DELETE FROM order_rule_overrides WHERE rule_key = ?",
                    (key,),
                )
                changed += max(0, int(cursor.rowcount or 0))

        if changed:
            conn.commit()

    return changed


def install_delta_mobile_legacy_catalog_tombstone_20261101() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import order_rules

    try:
        retire_stale_delta_mobile_custom_rows()
    except Exception:
        # Keep checkout available even if SQLite is briefly unavailable. The
        # registry read-time guard below still prevents stale rows from surfacing.
        pass

    rules = order_rules.ORDER_RULES
    if getattr(rules, "_delta_mobile_legacy_tombstone_installed", False):
        rules.invalidate()
        _INSTALLED = True
        return

    original_refresh = rules._refresh_external

    def _refresh_external_without_retired_mobile_rows() -> None:
        original_refresh()
        stale_keys = {
            key
            for key, rule in tuple(rules._custom_cache.items())
            if _is_retired_mobile_custom_rule(
                rule,
                rules._override_cache.get(key),
            )
        }
        stale_keys.update(
            key
            for key in _RETIRED_RULE_KEYS
            if key in rules._custom_cache or key in rules._override_cache
        )
        for key in stale_keys:
            rules._custom_cache.pop(key, None)
            rules._override_cache.pop(key, None)

    rules._refresh_external = _refresh_external_without_retired_mobile_rows
    rules._delta_mobile_legacy_tombstone_installed = True
    rules.invalidate()
    rules._refresh_external()
    _INSTALLED = True


__all__ = [
    "install_delta_mobile_legacy_catalog_tombstone_20261101",
    "retire_stale_delta_mobile_custom_rows",
]
