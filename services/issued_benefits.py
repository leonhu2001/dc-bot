from __future__ import annotations

"""Public facade for the generic issued-benefit engine.

The storage/lifecycle implementation lives in ``issued_benefits_legacy``.  This
facade keeps that implementation stable while adding policy fields that can
evolve without rewriting old issued snapshots.
"""

import sqlite3
from typing import Any

from services import issued_benefits_legacy as _legacy
from services.issued_benefits_legacy import *  # noqa: F401,F403


_base_normalize_rules = _legacy.normalize_rules
_base_describe_rules = _legacy.describe_rules

SERVICE_SCOPE_ONE_SEAT = "one_seat"
SERVICE_SCOPE_WHOLE_ORDER = "whole_order"
SUPPORTED_SERVICE_SCOPES = {
    SERVICE_SCOPE_ONE_SEAT,
    SERVICE_SCOPE_WHOLE_ORDER,
}


def normalize_rules(rules: dict[str, Any]) -> dict[str, Any]:
    source = dict(rules or {})
    normalized = _base_normalize_rules(source)

    effect_type = str(normalized.get("effect_type") or EFFECT_FIXED_CASH)
    scope = str(source.get("service_scope") or SERVICE_SCOPE_ONE_SEAT).strip()
    if scope not in SUPPORTED_SERVICE_SCOPES:
        raise ValueError("服務折抵範圍只能是一個陪玩席位或整張訂單。")
    normalized["service_scope"] = scope

    # 「整單免單」預設連指定費一起免；若未來真的需要只免服務費，
    # 可用固定金額/百分比模板精準描述，不讓「免單」語意模糊。
    if effect_type == EFFECT_FULL_ORDER and "include_specify_fee" not in source:
        normalized["include_specify_fee"] = True

    return normalized


# All preserved functions resolve normalize_rules from their original module
# globals at call time, so patching once keeps create/issue/resolve consistent.
_legacy.normalize_rules = normalize_rules


def get_issued_benefit(
    benefit_id: int,
    *,
    web_db=None,
) -> dict[str, Any] | None:
    """Direct id lookup; never depends on a recent-list pagination limit."""
    _legacy.ensure_issued_benefit_tables(web_db)
    path = _legacy._path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        _legacy._refresh_expired(conn, _legacy._now())
        row = conn.execute(
            "SELECT * FROM issued_benefits WHERE id=? LIMIT 1",
            (int(benefit_id),),
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    item = dict(row)
    item["rules"] = normalize_rules(_legacy._json(item.pop("rules_snapshot_json", "{}")))
    return item


def list_available_benefits_for_customer(
    customer_id: str,
    *,
    web_db=None,
) -> list[dict[str, Any]]:
    rows = _legacy.list_issued_benefits(
        customer_id=str(customer_id),
        status=STATUS_AVAILABLE,
        web_db=web_db,
        limit=1000,
    )
    for row in rows:
        row["rules"] = normalize_rules(row.get("rules") or {})
    return rows


def describe_rules(rules: dict[str, Any]) -> str:
    normalized = normalize_rules(rules)
    base = _base_describe_rules(normalized)
    effect = str(normalized.get("effect_type") or "")
    if effect in {EFFECT_SERVICE_HOURS, EFFECT_SERVICE_GAMES}:
        scope = str(normalized.get("service_scope") or SERVICE_SCOPE_ONE_SEAT)
        base += "｜" + ("整張單" if scope == SERVICE_SCOPE_WHOLE_ORDER else "單一陪玩席位")
    return base


_legacy.get_issued_benefit = get_issued_benefit
_legacy.list_available_benefits_for_customer = list_available_benefits_for_customer
_legacy.describe_rules = describe_rules
