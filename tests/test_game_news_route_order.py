from pathlib import Path


def test_official_game_news_router_precedes_game_tools_placeholder():
    source = Path("web/app/main.py").read_text(encoding="utf-8")

    assert "from web.app.routers.game_news import router as game_news_router" in source
    assert source.index("app.include_router(game_news_router)") < source.index(
        "app.include_router(game_tools_router)"
    )
