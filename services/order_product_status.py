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


def _available_public_categories():
    from services.order_rules import CATEGORY_LABELS
    from web.app.services import order_groups

    groups = order_groups.get_grouped_order_catalog("all")
    available = {
        str(group.get("category") or "")
        for group in groups
        if str(group.get("category") or "")
    }
    result = [{"key": "all", "label": "全部"}]
    for category in order_groups.CATEGORY_ORDER:
        if category not in available:
            continue
        result.append(
            {
                "key": category,
                "label": CATEGORY_LABELS.get(category, category),
            }
        )
    return result


def install_web_catalog_guards() -> None:
    """Install live availability checks before the site router imports helpers."""
    global _WEB_GUARDS_INSTALLED
    if _WEB_GUARDS_INSTALLED:
        return

    try:
        from web.app.services import order_groups

        order_groups.HIDDEN_PUBLIC_RULE_KEYS = StatusAwareHiddenRuleKeys(
            order_groups.HIDDEN_PUBLIC_RULE_KEYS
        )
        order_groups.get_public_order_categories = _available_public_categories

        from web.app.services import public_checkout

        public_checkout.PUBLIC_DISABLED_RULE_KEYS = StatusAwareHiddenRuleKeys(
            public_checkout.PUBLIC_DISABLED_RULE_KEYS
        )
    except Exception:
        return

    _WEB_GUARDS_INSTALLED = True


def _guarded_discord_details(
    category: str | None,
    group_label: str | None,
) -> list[dict]:
    from services.order_product_status import is_order_product_active

    if category is None or group_label is None:
        return []

    category_text = str(category)
    group_text = str(group_label)
    result: list[dict] = []

    # This function's code object is installed onto services.orders at runtime.
    # Resolve the effective manager-controlled group/name there as well, otherwise
    # the live availability guard would silently restore the old hard-coded label.
    for group in SELF_SERVICE_ORDER_CATALOG.get(category_text, []):
        fallback_label = str(group.get("label") or "")
        for detail in group.get("details", []):
            item = dict(detail)
            rule_key = str(item.get("rule_key") or "").strip()
            if (
                not rule_key
                or rule_key in CATALOG_HIDDEN_RULE_KEYS
                or not is_order_product_active(rule_key)
            ):
                continue

            rule = ORDER_RULES.get(rule_key)
            if rule is None:
                continue

            effective_group = _effective_builtin_group_label(
                rule,
                fallback_label,
            )
            if effective_group != group_text:
                continue

            manager_group_label = str(
                getattr(rule, "catalog_group_label", "") or ""
            ).strip()
            if manager_group_label:
                item["label"] = str(
                    getattr(rule, "label", "")
                    or item.get("label")
                    or ""
                )

            item["item"] = str(
                getattr(rule, "label", "")
                or item.get("label")
                or ""
            )
            result.append(item)

    for rule_key in _dynamic_admin_rule_keys(category_text):
        if (
            rule_key in CATALOG_HIDDEN_RULE_KEYS
            or not is_order_product_active(rule_key)
        ):
            continue
        rule = ORDER_RULES.get(rule_key)
        if rule is None:
            continue
        if _dynamic_admin_group_label(rule) != group_text:
            continue
        result.append(_dynamic_admin_detail(rule))

    return result


def _guarded_dynamic_group_get(self, category, default=None):
    category_text = str(category or "")
    catalog_groups = SELF_SERVICE_ORDER_CATALOG.get(category_text, [])
    candidate_labels: list[str] = []

    if catalog_groups:
        for group in catalog_groups:
            fallback_label = str(group.get("label") or "")
            details = list(group.get("details", []))

            if (
                not details
                and fallback_label
                and fallback_label not in candidate_labels
            ):
                candidate_labels.append(fallback_label)

            for detail in details:
                rule = ORDER_RULES.get(str(detail.get("rule_key") or ""))
                label = (
                    _effective_builtin_group_label(rule, fallback_label)
                    if rule is not None
                    else fallback_label
                )
                if label and label not in candidate_labels:
                    candidate_labels.append(label)
    else:
        candidate_labels = list(dict.get(self, category, default or []))

    for group_label in _dynamic_admin_group_labels(category_text):
        if group_label not in candidate_labels:
            candidate_labels.append(group_label)

    result = []
    for group_label in candidate_labels:
        if get_order_item_details_for_group(category_text, group_label):
            result.append(group_label)
    return result


def _guarded_self_service_rule(data: dict):
    from services.order_product_status import is_order_product_active
    from services.order_rules import ORDER_RULES, get_rule
    from services.orders import ORDER_RULE_KEY_BY_LABEL

    rule_key = str(data.get("order_rule_key") or "").strip()
    if rule_key:
        if not is_order_product_active(rule_key):
            raise ValueError("這個商品目前已下架，請重新選擇品項。")
        try:
            return get_rule(rule_key)
        except Exception:
            pass

    item_text = str(data.get("item") or "").strip()
    alias_rule_key = ORDER_RULE_KEY_BY_LABEL.get(item_text)
    if alias_rule_key:
        if not is_order_product_active(str(alias_rule_key)):
            raise ValueError("這個商品目前已下架，請重新選擇品項。")
        try:
            rule = get_rule(alias_rule_key)
            data["order_rule_key"] = rule.key
            return rule
        except Exception:
            pass

    for rule in ORDER_RULES.values():
        if str(rule.label) != item_text:
            continue
        if not is_order_product_active(str(rule.key)):
            raise ValueError("這個商品目前已下架，請重新選擇品項。")
        data["order_rule_key"] = rule.key
        return rule

    raise ValueError("找不到這個訂單項目的規則，請重新選擇品項。")


def install_discord_catalog_guards() -> None:
    """Patch imported catalog bindings in place so the running bot stays live."""
    global _DISCORD_GUARDS_INSTALLED
    if _DISCORD_GUARDS_INSTALLED:
        return

    try:
        from services import orders

        orders.CATALOG_HIDDEN_RULE_KEYS = StatusAwareHiddenRuleKeys(
            orders.CATALOG_HIDDEN_RULE_KEYS
        )
        orders.get_order_item_details_for_group.__code__ = (
            _guarded_discord_details.__code__
        )
        orders.DynamicOrderItemGroups.get.__code__ = (
            _guarded_dynamic_group_get.__code__
        )

        # self_service_runtime is imported before services.orders in bot.py.
        # Replacing the code object also updates the function binding already
        # imported into bot.py, so an already-selected product cannot be
        # submitted after a manager takes it offline.
        from services import self_service_runtime

        self_service_runtime._get_rule_from_self_service_data.__code__ = (
            _guarded_self_service_rule.__code__
        )
    except Exception:
        return

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
