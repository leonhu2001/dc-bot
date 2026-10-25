from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]

_METADATA_ONLY_CODES = {
    "tip_wallet_reference_mismatch",
    "worker_paid_without_paid_at",
    "cs_paid_without_paid_at",
}

_AUDITABILITY_CODES = {
    "wallet_order_reference_missing",
}


def _impact_hint(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    if code in _METADATA_ONLY_CODES:
        return "metadata-only candidate"
    if code in _AUDITABILITY_CODES:
        return "auditability warning"
    if str(issue.get("severity") or "").lower() == "warning":
        return "warning; verify context"
    return "financial/data mismatch candidate"


def main() -> None:
    snapshot = build_accounting_reconciliation_snapshot(
        ROOT,
        detail_limit=1000,
    )
    issues = list(snapshot.get("issues") or [])

    print("=== ACCOUNTING RECONCILIATION DIAGNOSTIC (READ ONLY) ===")
    print(f"ROOT: {ROOT}")
    print(f"STATUS: {snapshot.get('status')} / {snapshot.get('status_text')}")
    print(f"ISSUES: {snapshot.get('issue_count', 0)}")
    print(
        "SEVERITY: "
        f"critical={snapshot.get('critical_count', 0)} "
        f"warning={snapshot.get('warning_count', 0)}"
    )
    print(f"CATEGORY_COUNTS: {snapshot.get('category_counts', {})}")
    print(f"TRUNCATED: {snapshot.get('truncated', False)}")

    code_counts = Counter(str(item.get("code") or "-") for item in issues)
    print("CODE_COUNTS:")
    for code, count in sorted(code_counts.items()):
        print(f"  {code}: {count}")

    print("\nISSUE_DETAILS:")
    if not issues:
        print("  NONE")
    for index, issue in enumerate(issues, start=1):
        print(f"[{index:03d}] {issue.get('severity', '-')} | {issue.get('code', '-')}")
        print(f"  category: {issue.get('category', '-')}")
        print(f"  reference: {issue.get('reference', '-')}")
        print(f"  order_id: {issue.get('order_id')}")
        print(f"  title: {issue.get('title', '-')}")
        print(f"  expected: {issue.get('expected')!r}")
        print(f"  actual: {issue.get('actual')!r}")
        print(f"  repairable: {bool(issue.get('repairable'))}")
        print(f"  hint: {_impact_hint(issue)}")
        print(f"  detail: {issue.get('detail', '-')}")

    print("\nREAD_ONLY: this script does not modify either database.")


if __name__ == "__main__":
    main()
