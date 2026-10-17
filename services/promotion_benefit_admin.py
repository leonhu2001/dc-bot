from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from services import promotion_benefits as benefits


def _snapshot_for_template(
    *,
    template_id: int,
    name: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    return {
        "template_id": int(template_id),
        "name": str(name or "福利券"),
        "effect_kind": str(rules["effect_kind"]),
        "effect_value": float(rules["effect_value"]),
        "funding": str(rules["funding"]),
        "min_order_amount": int(rules["min_order_amount"]),
        "scope_type": str(rules["scope_type"]),
        "scope_values": list(rules["scope_values"]),
        "excluded_rule_keys": list(rules["excluded_rule_keys"]),
        "usage_limit": int(rules["usage_limit"]),
        "consume_mode": str(rules["consume_mode"]),
        "seat_mode": str(rules["seat_mode"]),
        "include_specify_fee": bool(rules["include_specify_fee"]),
        "allow_vip_discount": bool(rules["allow_vip_discount"]),
        "allow_points": bool(rules["allow_points"]),
        "is_high_risk": bool(rules["is_high_risk"]),
        "snapshot_version": 1,
    }


def update_template(
    template_id: int | str,
    *,
    name: str,
    rules: dict[str, Any],
    is_active: bool = True,
    sync_unused_issued: bool = False,
    actor_discord_id: str | int | None = None,
    web_db: str | Path | None = None,
) -> dict[str, int]:
    """Update a benefit template and optionally refresh untouched issued benefits.

    Existing issued benefits remain immutable by default. When the manager
    explicitly asks to sync, only benefits that are still active, have never
    been redeemed, are not currently reserved, and have not expired are updated.
    Their original issued/expiry timestamps are intentionally preserved.
    """
    benefits.ensure_promotion_benefit_tables(web_db)
    try:
        wanted = int(template_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("福利模板編號錯誤。") from exc

    title = str(name or "").strip()
    if not title:
        raise ValueError("請輸入福利模板名稱。")

    normalized = benefits._normalize_rules(rules)
    path = benefits._db_path(web_db)
    now = benefits._now_text()
    synced_count = 0

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        before = conn.execute(
            "SELECT * FROM promotion_benefit_templates WHERE id=? LIMIT 1",
            (wanted,),
        ).fetchone()
        if before is None:
            raise ValueError("找不到這個福利模板。")

        conn.execute(
            """
            UPDATE promotion_benefit_templates
            SET name=?, effect_kind=?, effect_value=?, funding=?,
                min_order_amount=?, scope_type=?, scope_json=?,
                excluded_rule_keys_json=?, valid_days=?, usage_limit=?,
                consume_mode=?, seat_mode=?, include_specify_fee=?,
                allow_vip_discount=?, allow_points=?, is_high_risk=?,
                is_active=?, updated_at=?
            WHERE id=?
            """,
            (
                title,
                normalized["effect_kind"],
                normalized["effect_value"],
                normalized["funding"],
                normalized["min_order_amount"],
                normalized["scope_type"],
                benefits._json_dump(normalized["scope_values"]),
                benefits._json_dump(normalized["excluded_rule_keys"]),
                normalized["valid_days"],
                normalized["usage_limit"],
                normalized["consume_mode"],
                normalized["seat_mode"],
                int(normalized["include_specify_fee"]),
                int(normalized["allow_vip_discount"]),
                int(normalized["allow_points"]),
                int(normalized["is_high_risk"]),
                int(bool(is_active)),
                now,
                wanted,
            ),
        )

        if sync_unused_issued:
            snapshot = _snapshot_for_template(
                template_id=wanted,
                name=title,
                rules=normalized,
            )
            remaining_value = (
                float(normalized["effect_value"])
                if normalized["consume_mode"] == "balance"
                and normalized["effect_kind"] == benefits.EFFECT_FIXED_CASH
                else None
            )
            cur = conn.execute(
                """
                UPDATE promotion_issued_benefits
                SET title=?, rules_snapshot_json=?, remaining_uses=?, remaining_value=?
                WHERE template_id=?
                  AND status='active'
                  AND reserved_order_id IS NULL
                  AND redeemed_order_id IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (
                    title,
                    benefits._json_dump(snapshot),
                    int(normalized["usage_limit"]),
                    remaining_value,
                    wanted,
                    now,
                ),
            )
            synced_count = int(cur.rowcount or 0)

        before_payload = dict(before)
        before_payload["scope_values"] = benefits._json_load(
            before_payload.pop("scope_json", "[]"), []
        )
        before_payload["excluded_rule_keys"] = benefits._json_load(
            before_payload.pop("excluded_rule_keys_json", "[]"), []
        )
        conn.execute(
            """
            INSERT INTO promotion_benefit_audit (
                action, template_id, actor_discord_id, detail_json, created_at
            ) VALUES ('template_updated', ?, ?, ?, ?)
            """,
            (
                wanted,
                str(actor_discord_id or ""),
                benefits._json_dump(
                    {
                        "before": before_payload,
                        "after": {
                            "name": title,
                            **normalized,
                            "is_active": bool(is_active),
                        },
                        "sync_unused_issued": bool(sync_unused_issued),
                        "synced_issued_count": synced_count,
                    }
                ),
                now,
            ),
        )
        conn.commit()

    return {"template_id": wanted, "synced_count": synced_count}
