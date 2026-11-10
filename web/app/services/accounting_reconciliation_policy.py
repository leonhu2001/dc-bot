from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from services.one_companion_one_guard_payout import is_full_worker_payout_rule
from services.staff_internal_ammo_dump_policy import calculate_internal_ammo_dump_cs_payout
from services.farm_fixed_cut_policy import (
    is_public_farm_fixed_cut_rule,
    calculate_farm_fixed_cut_settlement,
)
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



# Two archived November repairs are narrow exceptions to obsolete legacy flags.
# The archived backups, October performance and payout rows were verified before
# the repair. Never apply this shortcut to arbitrary orders or unrelated audits.
_VERIFIED_NOV_BONUS_REPAIRS = {
    298: {
        "order_no": "MO20261102001",
        "worker_id": "1029311167212036116",
        "gross_share": 720,
        "worker_before": 576, "worker_after": 590,
        "cs_before": 72, "cs_after": 68,
    },
    300: {
        "order_no": "MO20261103002",
        "worker_id": "1029311167212036116",
        "gross_share": 450,
        "worker_before": 360, "worker_after": 369,
        "cs_before": 45, "cs_after": 43,
    },
}


def _is_verified_nov_bonus_repair(conn: sqlite3.Connection, order_id: int) -> bool:
    """Allow only matching audit-verified 2% corrections past legacy policy flags.

    No financial data is changed. A changed ledger row, amount, identity, note,
    manual override, or missing/duplicate audit must retain its anomaly.
    """
    spec = _VERIFIED_NOV_BONUS_REPAIRS.get(int(order_id))
    if spec is None or not _table_exists(conn, "admin_audit_logs"):
        return False
    try:
        order = conn.execute(
            "SELECT bot_order_no, status FROM web_orders WHERE id=?",
            (int(order_id),),
        ).fetchone()
        if (order is None
                or _normalize(order["bot_order_no"]) != spec["order_no"]
                or _normalize(order["status"]).lower() != "closed"):
            return False

        worker_rows = conn.execute(
            "SELECT worker_discord_id, gross_share, final_payout, note "
            "FROM worker_payouts WHERE order_id=?",
            (int(order_id),),
        ).fetchall()
        # Several approved orders contain more than one worker. The 2% audit
        # targets exactly one ID; all other rows must still match their own
        # documented rate (or the original unannotated base 80%).
        if not 1 <= len(worker_rows) <= 4:
            return False
        matches = [
            row for row in worker_rows
            if str(row["worker_discord_id"]) == spec["worker_id"]
        ]
        if len(matches) != 1:
            return False
        worker = matches[0]
        for other in worker_rows:
            if other is worker:
                continue
            other_note = _normalize(other["note"])
            other_rate = _rate_from_persisted_note(other_note)
            if other_rate is None and not other_note:
                other_rate = 0.80
            if (other_rate is None
                    or not _money_equal(
                        other["final_payout"],
                        round(_as_float(other["gross_share"]) * other_rate),
                    )):
                return False
        note = _normalize(worker["note"])
        rate = _rate_from_persisted_note(note)
        if (str(worker["worker_discord_id"]) != spec["worker_id"]
                or not _money_equal(worker["gross_share"], spec["gross_share"])
                or not _money_equal(worker["final_payout"], spec["worker_after"])
                or "前月業績達5000T 2%" not in note
                or "前月業績 13801T" not in note
                or rate is None or abs(rate - 0.82) > 1e-9):
            return False

        cs_rows = conn.execute(
            "SELECT payout_amount FROM customer_service_payouts "
            "WHERE order_id=?", (int(order_id),),
        ).fetchall()
        if len(cs_rows) != 1 or not _money_equal(
            cs_rows[0]["payout_amount"], spec["cs_after"],
        ):
            return False

        if _table_exists(conn, "worker_payout_overrides"):
            override = conn.execute(
                "SELECT 1 FROM worker_payout_overrides "
                "WHERE order_id=? AND worker_discord_id=? LIMIT 1",
                (int(order_id), spec["worker_id"]),
            ).fetchone()
            if override is not None:
                return False

        audits = conn.execute(
            "SELECT before_json, after_json FROM admin_audit_logs "
            "WHERE action='restore_november_bonus_verified_20261110' "
            "AND target_type='order' AND target_id=?",
            (str(order_id),),
        ).fetchall()
        if len(audits) != 1:
            return False

        before = json.loads(str(audits[0]["before_json"] or "{}"))
        after = json.loads(str(audits[0]["after_json"] or "{}"))
        return (
            before == {
                "worker": spec["worker_before"], "cs": spec["cs_before"],
            }
            and after == {
                "worker": spec["worker_after"], "cs": spec["cs_after"],
            }
        )
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        return False


def _rate_from_persisted_note(note: Any) -> float | None:
    text = _normalize(note)
    if "特殊代肝單｜接單人員全額 100%" in text:
        return 1.0
    if "固定店抽" in text and ("員工" in text or "固定店抽代肝" in text):
        return 1.0
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
    if ("前月已結算薪資達5000T 2%" in text
            or "前月業績達5000T 2%" in text):
        rate += 0.02

    rate = min(0.87, rate)
    if "綁店3%" in text:
        rate = min(0.90, rate + 0.03)
    return rate


def _policy_consistency_for_order(
    conn: sqlite3.Connection,
    order_id: int,
) -> dict[str, bool]:
    order_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(web_orders)").fetchall()
    }
    rule_column = "order_rule_key" if "order_rule_key" in order_columns else "NULL AS order_rule_key"
    order = conn.execute(
        f"""
        SELECT id, status, amount, payout_base_amount, price_snapshot_json, {rule_column},
               {("customer_pay_amount" if "customer_pay_amount" in order_columns else "amount AS customer_pay_amount")}
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
    # Legacy snapshot flags can predate the independently audited 2% payout
    # correction. Only verified audit+ledger evidence permits the newer bonus
    # calculation for these two orders.
    verified_bonus_order = _is_verified_nov_bonus_repair(conn, order_id)
    new_policy = (not legacy) or verified_bonus_order
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
        if (rate is None
                and verified_bonus_order
                and _normalize(row["note"]) == ""
                and str(row["worker_discord_id"]) !=
                    _VERIFIED_NOV_BONUS_REPAIRS[int(order_id)]["worker_id"]):
            # The pre-repair base calculation sometimes cleared other
            # workers' ordinary 80% notes. It may be inferred ONLY after
            # verifying every worker, the target 2% row and its audit.
            rate = 0.80
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
            if is_public_farm_fixed_cut_rule(order["order_rule_key"]):
                try:
                    settlement = calculate_farm_fixed_cut_settlement(
                        order["order_rule_key"],
                        order["customer_pay_amount"]
                        if order["customer_pay_amount"] is not None else order["amount"],
                        payout_base,
                    )
                    expected_cs = settlement.customer_service_amount
                except (ValueError, TypeError):
                    expected_cs = -1  # preserve anomaly for malformed ledger
            elif is_full_worker_payout_rule(order["order_rule_key"]):
                expected_cs = calculate_internal_ammo_dump_cs_payout(
                    order["order_rule_key"],
                    order["customer_pay_amount"]
                    if order["customer_pay_amount"] is not None else order["amount"],
                    payout_base,
                )
            else:
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
