from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_restock_sort_has_server_data_and_client_ordering() -> None:
    template = (ROOT / "web" / "app" / "templates" / "game_market.html").read_text(
        encoding="utf-8"
    )
    script = (
        ROOT / "web" / "app" / "static" / "js" / "pages" / "game_market_live.js"
    ).read_text(encoding="utf-8")

    assert 'data-market-restock-at=' in template
    assert 'data-market-restock-confidence=' in template
    assert "pageParams.get('sort') === 'restock_asc'" in script
    assert "applyClientSort();" in script
    assert "marketRestockAt" in script
    assert "marketRestockConfidence" in script
