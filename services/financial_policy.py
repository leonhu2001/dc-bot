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


def _preview_and_finance(value: Any) -> tuple[dict, dict]:
    snapshot = _snapshot_dict(value)
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    if not isinstance(preview, dict):
        preview = {}
    finance = preview.get("finance") if isinstance(preview.get("finance"), dict) else preview
    if not isinstance(finance, dict):
        finance = {}
    return preview, finance


def financial_policy_version_from_snapshot(value: Any) -> str:
    preview, finance = _preview_and_finance(value)
    return str(
        finance.get("financial_policy_version")
        or preview.get("financial_policy_version")
        or ""
    ).strip()


def uses_current_financial_policy(value: Any) -> bool:
    preview, finance = _preview_and_finance(value)
    if str(
        finance.get("financial_policy_version")
        or preview.get("financial_policy_version")
        or ""
    ).strip() == FINANCIAL_POLICY_VERSION:
        return True

    # Web checkout facade always writes these two fields, even when no custom
    # benefit is selected. They did not exist in old snapshots, making them a
    # safe compatibility marker without changing the public payload schema.
    return (
        "issued_benefit_service_value" in finance
        and "benefit_store_absorbed_amount" in finance
    )
