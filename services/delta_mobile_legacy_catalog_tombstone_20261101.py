from __future__ import annotations

import json
import sqlite3
from pathlib import Path


_INSTALLED = False
_MOBILE_CATEGORY = "delta_mobile_basic"
_RETIRED_GROUP_LABELS = frozenset({
    "技術陪",
    "體驗單",
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

    group_label = _effective_group_label(rule, override_item)
    if group_label in _RETIRED_GROUP_LABELS:
        return True

    # Very old manager rows may have no catalog_group_label and only carry their
    # display name. Keep the match intentionally narrow to the products being
    # replaced in this release.
    label = str(getattr(rule, "label", "") or "").strip()
    return (
        "絕巴技術陪" in label
        or (
            "體驗單" in label
            and "護航體驗單" not in label
        )
        or "技術陪〈手遊〉" in label
        or "手遊｜技術陪" in label
    )


def retire_stale_delta_mobile_custom_rows(
    db_file: str | Path | None = None,
) -> int:
    """Deactivate replaced manager products while retaining full audit history."""
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

            retired = group_label in _RETIRED_GROUP_LABELS
            if not retired and not group_label:
                retired = (
                    "絕巴技術陪" in label
                    or (
                        "體驗單" in label
                        and "護航體驗單" not in label
                    )
                    or "技術陪〈手遊〉" in label
                    or "手遊｜技術陪" in label
                )

            if retired:
                stale_keys.append(key)

        if stale_keys:
            conn.executemany(
                "UPDATE custom_order_rules SET is_active = 0 WHERE rule_key = ?",
                [(key,) for key in stale_keys],
            )
            conn.commit()

    return len(stale_keys)


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
        stale_keys = [
            key
            for key, rule in tuple(rules._custom_cache.items())
            if _is_retired_mobile_custom_rule(
                rule,
                rules._override_cache.get(key),
            )
        ]
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
