from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_poll_runtime_state_is_ignored_without_weakening_deploy_guards():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts/deploy_main.sh").read_text(encoding="utf-8")
    assert "data/market_poll_state.json" in ignore
    assert "data/(deployed_version|market_poll_state)" in deploy
    assert "git status --porcelain --untracked-files=all" in deploy
    assert "if [ -n \"$DIRTY_WORKTREE\" ]; then" in deploy
    assert "git reset --hard \"$TARGET\"" in deploy
    assert "rm -f \"$APP/data/market_poll_state.json\"" not in deploy


def test_market_summary_is_inside_chart_band_and_has_no_duplicate_current_price():
    page = (ROOT / "web/app/templates/game_market_item.html").read_text(encoding="utf-8")
    js = (ROOT / "web/app/static/js/pages/game_market_item.js").read_text(encoding="utf-8")
    assert page.count('data-market-summary') == 1
    assert page.count('data-market-chart-kpis') == 0
    assert 'class="market-item-stats"' not in page
    assert page.index('data-market-chart') < page.index('data-market-summary') < page.index('data-market-chart-stage')
    for metric in ["24H 漲跌", "24H 區間", "7D 均價", "7D 區間", "歷史覆蓋"]:
        assert page.count(metric) == 1
    assert "data-market-chart-last" not in page
    assert "data-market-change-24h" in page
    assert "data-market-coverage-note" in page
    assert "chartKpis" not in js
