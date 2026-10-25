from __future__ import annotations

from web.app.routers import admin_ai_operations as module


def test_ai_operations_uses_policy_aware_accounting_snapshot(monkeypatch) -> None:
    raw_issue = {
        "source": "accounting",
        "category": "accounting",
        "category_label": "帳務對帳",
        "code": "worker_payout_amount_mismatch",
        "severity": "critical",
        "reference": "MO-TEST",
        "title": "接單人員分潤金額不一致",
        "detail": "raw payout mismatch",
        "order_id": 1,
        "age_minutes": None,
    }

    monkeypatch.setattr(
        module,
        "build_safe_operations_snapshot",
        lambda period: {
            "anomalies": {
                "status": "critical",
                "issue_count": 1,
                "critical_count": 1,
                "warning_count": 0,
                "category_counts": {"accounting": 1},
                "issues": [],
            }
        },
    )
    monkeypatch.setattr(
        module,
        "build_anomaly_snapshot",
        lambda limit=80: {
            "status": "critical",
            "status_text": "需要處理",
            "issue_count": 1,
            "critical_count": 1,
            "warning_count": 0,
            "repairable_count": 1,
            "category_counts": {"accounting": 1},
            "issues": [dict(raw_issue)],
            "visible_count": 1,
            "truncated": False,
        },
    )
    monkeypatch.setattr(
        module,
        "build_accounting_policy_view",
        lambda detail_limit=10000: (
            {
                "status": "ok",
                "issue_count": 0,
                "critical_count": 0,
                "warning_count": 0,
                "issues": [],
            },
            [dict(raw_issue)],
        ),
    )

    snapshot = module._build_policy_aware_operations_snapshot("quarter")
    anomalies = snapshot["anomalies"]

    assert anomalies["status"] == "ok"
    assert anomalies["issue_count"] == 0
    assert anomalies["critical_count"] == 0
    assert anomalies["category_counts"]["accounting"] == 0
    assert anomalies["accounting_issue_count"] == 0
    assert anomalies["issues"] == []
