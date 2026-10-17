from __future__ import annotations

import json
from typing import Any


FINANCIAL_POLICY_VERSION = "2026-10-17-shared-fixed-cs-margin-v1"


def _snapshot_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def financial_policy_version_from_snapshot(value: Any) -> str:
    snapshot = _snapshot_dict(value)
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    finance = preview.get("finance") if isinstance(preview, dict) and isinstance(preview.get("finance"), dict) else {}
    return str(
        finance.get("financial_policy_version")
        or preview.get("financial_policy_version") if isinstance(preview, dict) else ""
    ).strip()


def uses_current_financial_policy(value: Any) -> bool:
    return financial_policy_version_from_snapshot(value) == FINANCIAL_POLICY_VERSION
