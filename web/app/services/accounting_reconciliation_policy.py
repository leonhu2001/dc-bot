from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shared.payout import (
    CUSTOMER_SERVICE_PAYOUT_RATE,
    LEGACY_CUSTOMER_SERVICE_POLICY,
    calculate_customer_service_payout,
    calculate_customer_service_payout_base_amount,
)
from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


PAYOUT_AMOUNT_MISMATCH_CODES = {
    "worker_payout_amount_mismatch",
    "customer_service_payout_amount_mismatch",
}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=3.0,
        )
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(table),),
    ).fetchone()
    return row is not None


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _money_equal(left: Any, right: Any, tolerance: float = 0.01) -> bool:
    return abs(_as_float(left) - _as_float(right)) <= float(tolerance)


def _finance_snapshot(value: Any) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(value or "{}"))
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    if not isinstance(preview, dict):
        return {}
    finance = preview.get("finance")
    return finance if isinstance(finance, dict) else {}


def _is_legacy_snapshot(value: Any) -> bool:
    return (
        _normalize(_finance_snapshot(value).get("customer_service_payout_policy"))
        == LEGACY_CUSTOMER_SERVICE_POLICY
    )


def _report_state(conn: sqlite3.Connection, order_id: int) -> tuple[str, bool] | None:
    if not _table_exists(conn, "order_reports"):
        return None

    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(order_reports)").fetchall()
    }
    if "order_id" not in columns or "status" not in columns:
        return None

    legacy_expr = "COALESCE(is_legacy, 0)" if "is_legacy" in columns else "0"
    row = conn.execute(
        f"""
        SELECT status, {legacy_expr} AS is_legacy
        FROM order_reports
        WHERE order_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(order_id),),
    ).fetchone()
    if row is None:
        return ("", False)
    return (_normalize(row["status"]).lower(), bool(row["is_legacy"]))


def _rate_from_persisted_note(note: Any) -> float | None:
    text = _normalize(note)
    if "分潤：基礎80%" not in text:
        return None

    rate = 0.80
    if "掛名5%" in text:
        rate += 0.05
        return rate

    if "掛名3%" in text:
        rate += 0.03
    if "直播2%" in text:
        rate += 0.02
    if "前月已結算薪資達5000T 2%" in text:
        rate += 0.02

    rate = min(0.87, rate)
    if "綁店3%" in text:
        rate = min(0.90, rate + 0.03)
    return rate


def _policy_consistency_for_order(
    conn: sqlite3.Connection,
    order_id: int,
) -> dict[str, bool]:
    order = conn.execute(
        """
        SELECT id, status, amount, payout_base_amount, price_snapshot_json
        FROM web_orders
        WHERE id = ?
        LIMIT 1
        """,
        (int(order_id),),
    ).fetchone()
    if order is None:
        return {
            "new_policy": False,
            "provisional": False,
            "worker_consistent": False,
            "cs_consistent": False,
        }

    report_state = _report_state(conn, int(order_id))
    if report_state is None:
        return {
            "new_policy": False,
            "provisional": False,
            "worker_consistent": False,
            "cs_consistent": False,
        }

    report_status, report_legacy = report_state
    legacy = bool(report_legacy) or _is_legacy_snapshot(order["price_snapshot_json"])
    new_policy = not legacy
    if not new_policy:
        return {
            "new_policy": False,
            "provisional": False,
            "worker_consistent": False,
            "cs_consistent": False,
        }

    # New-policy payouts are provisional until the report is approved. Closing
    # an order creates the base rows first; report approval then freezes the
    # reviewed named/stream/previous-month/store-binding bonuses.
    if report_status != "approved":
        return {
            "new_policy": True,
            "provisional": True,
            "worker_consistent": False,
            "cs_consistent": False,
        }

    worker_rows = conn.execute(
        """
        SELECT worker_discord_id, gross_share, final_payout, note
        FROM worker_payouts
        WHERE order_id = ?
        ORDER BY id ASC
        """,
        (int(order_id),),
    ).fetchall()

    worker_consistent = bool(worker_rows)
    total_worker = 0
    for row in worker_rows:
        rate = _rate_from_persisted_note(row["note"])
        if rate is None:
            worker_consistent = False
            break
        gross = max(0.0, _as_float(row["gross_share"]))
        expected = int(round(gross * rate))
        actual = _as_float(row["final_payout"])
        if not _money_equal(expected, actual):
            worker_consistent = False
            break
        total_worker += max(0, int(round(actual)))

    cs_consistent = False
    if worker_consistent:
        cs_rows = conn.execute(
            """
            SELECT payout_amount
            FROM customer_service_payouts
            WHERE order_id = ?
            ORDER BY id ASC
            """,
            (int(order_id),),
        ).fetchall()
        if len(cs_rows) == 1:
            payout_base = max(
                0,
                int(order["payout_base_amount"] or order["amount"] or 0),
            )
            cs_base = calculate_customer_service_payout_base_amount(
                payout_base_amount=payout_base,
                price_snapshot_json=order["price_snapshot_json"],
            )
            effective_worker_rate = (
                min(1.0, total_worker / payout_base)
                if payout_base > 0
                else 0.80
            )
            expected_cs = int(
                round(
                    calculate_customer_service_payout(
                        int(cs_base),
                        CUSTOMER_SERVICE_PAYOUT_RATE,
                        effective_worker_rate=effective_worker_rate,
                    )
                )
            )
            cs_consistent = _money_equal(
                expected_cs,
                cs_rows[0]["payout_amount"],
            )

    return {
        "new_policy": True,
        "provisional": False,
        "worker_consistent": worker_consistent,
        "cs_consistent": cs_consistent,
    }


def _should_suppress_amount_mismatch(
    item: dict[str, Any],
    state: dict[str, bool],
) -> bool:
    code = _normalize(item.get("code"))
    if code not in PAYOUT_AMOUNT_MISMATCH_CODES or not state.get("new_policy"):
        return False
    if state.get("provisional"):
        return True
    if code == "worker_payout_amount_mismatch":
        return bool(state.get("worker_consistent"))
    if code == "customer_service_payout_amount_mismatch":
        return bool(state.get("cs_consistent"))
    return False


def _issue_fingerprint(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _normalize(item.get("code")),
        _normalize(item.get("order_id")),
        _normalize(item.get("reference")),
        _normalize(item.get("detail")),
        _normalize(item.get("severity")),
    )


def _summarize_accounting_snapshot(
    raw: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    detail_limit: int,
) -> dict[str, Any]:
    category_counts: dict[str, int] = defaultdict(int)
    severity_counts: dict[str, int] = defaultdict(int)
    for item in issues:
        category_counts[_normalize(item.get("category"))] += 1
        severity_counts[_normalize(item.get("severity"))] += 1

    critical_count = int(severity_counts.get("critical", 0))
    warning_count = int(severity_counts.get("warning", 0))
    if critical_count:
        status = "critical"
        status_text = "需要處理"
    elif warning_count:
        status = "warning"
        status_text = "有注意事項"
    else:
        status = "ok"
        status_text = "帳務一致"

    limit = max(0, int(detail_limit or 0))
    result = dict(raw)
    result.update(
        {
            "status": status,
            "status_text": status_text,
            "issue_count": len(issues),
            "repairable_count": sum(1 for item in issues if item.get("repairable")),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "category_counts": dict(category_counts),
            "issues": issues[:limit],
            "truncated": len(issues) > limit,
        }
    )
    return result


def build_accounting_policy_view(
    root: Path | None = None,
    *,
    detail_limit: int = 200,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(root or _repository_root())
    # Pull enough raw detail to recalculate the summary after removing only
    # known lifecycle/policy false positives. Normal reconciliation findings
    # remain untouched.
    raw = build_accounting_reconciliation_snapshot(root, detail_limit=10000)
    raw_issues = list(raw.get("issues") or [])

    conn = _connect_readonly(root / "web_dashboard.db")
    if conn is None or not _table_exists(conn, "web_orders"):
        if conn is not None:
            conn.close()
        return _summarize_accounting_snapshot(
            raw,
            raw_issues,
            detail_limit=detail_limit,
        ), []

    states: dict[int, dict[str, bool]] = {}
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    try:
        for item in raw_issues:
            code = _normalize(item.get("code"))
            raw_order_id = item.get("order_id")
            if code not in PAYOUT_AMOUNT_MISMATCH_CODES or raw_order_id in (None, ""):
                kept.append(item)
                continue

            try:
                order_id = int(raw_order_id)
            except (TypeError, ValueError):
                kept.append(item)
                continue

            if order_id not in states:
                states[order_id] = _policy_consistency_for_order(conn, order_id)

            if _should_suppress_amount_mismatch(item, states[order_id]):
                suppressed.append(item)
            else:
                kept.append(item)
    finally:
        conn.close()

    return _summarize_accounting_snapshot(
        raw,
        kept,
        detail_limit=detail_limit,
    ), suppressed


def build_policy_aware_accounting_reconciliation_snapshot(
    root: Path | None = None,
    *,
    detail_limit: int = 200,
) -> dict[str, Any]:
    snapshot, _ = build_accounting_policy_view(
        root,
        detail_limit=detail_limit,
    )
    return snapshot


def normalize_anomaly_snapshot(
    snapshot: dict[str, Any],
    suppressed_accounting_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    if not suppressed_accounting_issues:
        return snapshot

    counters = Counter(_issue_fingerprint(item) for item in suppressed_accounting_issues)
    visible: list[dict[str, Any]] = []
    for item in list(snapshot.get("issues") or []):
        fingerprint = _issue_fingerprint(item)
        if str(item.get("source") or "") == "accounting" and counters.get(fingerprint, 0) > 0:
            counters[fingerprint] -= 1
            continue
        visible.append(item)

    suppressed_critical = sum(
        1 for item in suppressed_accounting_issues
        if _normalize(item.get("severity")) == "critical"
    )
    suppressed_warning = sum(
        1 for item in suppressed_accounting_issues
        if _normalize(item.get("severity")) == "warning"
    )
    suppressed_repairable = sum(
        1 for item in suppressed_accounting_issues
        if item.get("repairable")
    )

    result = dict(snapshot)
    result["issues"] = visible
    result["issue_count"] = max(
        0,
        int(snapshot.get("issue_count") or 0) - len(suppressed_accounting_issues),
    )
    result["critical_count"] = max(
        0,
        int(snapshot.get("critical_count") or 0) - suppressed_critical,
    )
    result["warning_count"] = max(
        0,
        int(snapshot.get("warning_count") or 0) - suppressed_warning,
    )
    result["repairable_count"] = max(
        0,
        int(snapshot.get("repairable_count") or 0) - suppressed_repairable,
    )
    result["accounting_issue_count"] = max(
        0,
        int(snapshot.get("accounting_issue_count") or 0) - len(suppressed_accounting_issues),
    )
    category_counts = dict(snapshot.get("category_counts") or {})
    if "accounting" in category_counts:
        category_counts["accounting"] = max(
            0,
            int(category_counts.get("accounting") or 0) - len(suppressed_accounting_issues),
        )
    result["category_counts"] = category_counts
    result["visible_count"] = len(visible)
    result["truncated"] = result["issue_count"] > len(visible)

    if result["critical_count"] > 0:
        result["status"] = "critical"
        result["status_text"] = "需要處理"
    elif result["warning_count"] > 0:
        result["status"] = "warning"
        result["status_text"] = "有注意事項"
    else:
        result["status"] = "ok"
        result["status_text"] = "目前正常"
    return result


def normalize_system_health_snapshot(
    health: dict[str, Any],
    accounting: dict[str, Any],
) -> dict[str, Any]:
    result = dict(health)
    result["accounting"] = accounting

    metrics = dict(health.get("metrics") or {})
    metrics["accounting_issues"] = int(accounting.get("issue_count") or 0)
    metrics["accounting_critical"] = int(accounting.get("critical_count") or 0)
    result["metrics"] = metrics

    alerts = [
        dict(item)
        for item in list(health.get("alerts") or [])
        if not _normalize(item.get("message")).startswith("帳務對帳偵測到")
    ]
    issue_count = int(accounting.get("issue_count") or 0)
    critical_count = int(accounting.get("critical_count") or 0)
    if issue_count > 0:
        alerts.append(
            {
                "severity": "critical" if critical_count > 0 else "warning",
                "message": f"帳務對帳偵測到 {issue_count} 筆差異（Critical {critical_count} 筆）。",
            }
        )
    result["alerts"] = alerts

    severities = {_normalize(item.get("severity")) for item in alerts}
    if "critical" in severities:
        result["overall"] = "critical"
        result["overall_text"] = "需要處理"
    elif "warning" in severities:
        result["overall"] = "warning"
        result["overall_text"] = "有注意事項"
    else:
        result["overall"] = "ok"
        result["overall_text"] = "系統正常"
    return result
