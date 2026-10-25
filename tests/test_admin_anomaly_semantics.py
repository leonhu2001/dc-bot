from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_accounting_issue_count_has_one_canonical_reconciliation_source() -> None:
    anomaly_source = (ROOT / "web/app/services/anomaly_detection.py").read_text(
        encoding="utf-8"
    )
    system_source = (ROOT / "web/app/services/system_health.py").read_text(
        encoding="utf-8"
    )

    assert "build_accounting_reconciliation_snapshot" in anomaly_source
    assert '"accounting_issue_count": int(accounting.get("issue_count") or 0)' in anomaly_source
    assert "build_accounting_reconciliation_snapshot" in system_source
    assert '"accounting_issues": accounting.get("issue_count")' in system_source


def test_ai_operations_does_not_present_total_anomalies_as_accounting() -> None:
    template = (ROOT / "web/app/templates/admin_ai_operations.html").read_text(
        encoding="utf-8"
    )
    router = (ROOT / "web/app/routers/admin_ai_operations.py").read_text(
        encoding="utf-8"
    )

    assert "異常中心（全部類別）" in template
    assert "不等於帳務異常數" in template
    assert "帳務對帳異常" in template
    assert "anomalies.category_counts.get('accounting', 0)" in template
    assert "/admin/accounting-reconciliation" in template

    assert 'anomalies["accounting_issue_count"]' in router
    assert 'category_counts.get("accounting")' in router
    assert '"anomalies.issue_count"' in router
    assert "不可稱為帳務異常數" in router
    assert '"anomalies.accounting_issue_count"' in router
    assert "與系統維運的帳務對帳指標同源" in router
    assert router.count("_clarify_anomaly_semantics(snapshot)") == 2
