from __future__ import annotations

import json
from typing import Any, Mapping

ANONYMOUS_BOSS_LABEL = "匿名老闆"
ANONYMOUS_CUSTOMER_KEY = "anonymous_customer_name"


def customer_name_is_anonymous(data: Mapping[str, Any] | None) -> bool:
    """Explicit staff choice only; older orders remain non-anonymous."""
    return bool(isinstance(data, Mapping) and data.get(ANONYMOUS_CUSTOMER_KEY) is True)


def customer_name_is_anonymous_in_snapshot(raw: Any) -> bool:
    """Read the durable per-order visibility flag without changing legal identity."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return False
    return customer_name_is_anonymous(raw)


def public_customer_display_name(real_name: str, *, anonymous: bool) -> str:
    return ANONYMOUS_BOSS_LABEL if anonymous else real_name
