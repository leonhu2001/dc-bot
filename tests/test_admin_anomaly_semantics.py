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


def test_ai_operations_shows_anomaly_breakdown_and_full_detail_link() -> None:
    template = (ROOT / "web/app/templates/admin_ai_operations.html").read_text(
        encoding="utf-8"
    )

    for category in ("order", "payment", "sync", "topup", "support", "accounting"):
        assert f"anomalies.category_counts.get('{category}', 0)" in template

    assert "訂單 {{ order_issues }}" in template
    assert "付款 {{ payment_issues }}" in template
    assert "同步 {{ sync_issues }}" in template
    assert "儲值 {{ topup_issues }}" in template
    assert "客服 {{ support_issues }}" in template
    assert "帳務 {{ accounting_issues }}" in template
    assert "Critical {{ anomalies.critical_count }}" in template
    assert "Warning {{ anomalies.warning_count }}" in template
    assert 'href="/admin/anomalies"' in template
    assert "查看 {{ anomalies.issue_count }} 筆異常明細" in template
