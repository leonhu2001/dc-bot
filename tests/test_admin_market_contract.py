from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_market_monitoring_workspace_is_manager_visible():
    router = _read("web/app/routers/admin_anomalies.py")
    template = _read("web/app/templates/admin_market.html")
    sidebar = _read("web/app/templates/_admin_sidebar.html")

    assert '@router.get("/admin/market")' in router
    assert "check_market_health" in router
    assert 'href="/admin/market"' in sidebar
    assert "市場監控" in sidebar

    assert "成熟補貨預測" in template
    assert "待驗證預測" in template
    assert "已回測預測" in template
    assert "平均預測誤差" in template
    assert "補貨 DM 已送達" in template
    assert "DM 重試 / 失敗" in template
