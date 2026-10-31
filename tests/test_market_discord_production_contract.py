from pathlib import Path

from services.market.discord_runtime import _market_database_url


ROOT = Path(__file__).resolve().parents[1]


def test_discord_runtime_prefers_dedicated_market_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    web_dir = tmp_path / "web"
    data_dir.mkdir()
    web_dir.mkdir()
    (data_dir / "market_discord.env").write_text(
        "MARKET_DATABASE_URL=postgresql+psycopg2://bot:secret@127.0.0.1/market\n",
        encoding="utf-8",
    )
    (web_dir / ".env").write_text(
        "MARKET_DATABASE_URL=postgresql+psycopg2://web:other@127.0.0.1/market\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("MARKET_DATABASE_URL", raising=False)
    monkeypatch.delenv("MARKET_DISCORD_ENV_FILE", raising=False)
    monkeypatch.setenv("APP_DIR", str(tmp_path))

    assert _market_database_url() == (
        "postgresql+psycopg2://bot:secret@127.0.0.1/market"
    )


def test_discord_market_setup_uses_least_secret_and_rolls_back():
    shell = (ROOT / "scripts" / "setup_market_discord_production.sh").read_text(
        encoding="utf-8"
    )
    powershell = (
        ROOT / "scripts" / "setup_market_discord_production.ps1"
    ).read_text(encoding="utf-8")

    assert 'BOT_ENV="$APP/data/market_discord.env"' in shell
    assert 'TARGET_CHANNEL="1566004926209990776"' in shell
    assert 'install -o "$BOT_USER" -g "$BOT_GROUP" -m 0600' in shell
    assert 'MARKET_DATABASE_URL' in shell
    assert 'WEB_PUSH_VAPID_PRIVATE_KEY' not in shell
    assert 'DISCORD_TOKEN' not in shell
    assert 'cp -a "$BACKUP_DIR/market_discord.env" "$BOT_ENV"' in shell
    assert 'rm -f "$BOT_ENV"' in shell
    assert 'panels synced channel=$TARGET_CHANNEL' in shell
    assert "date '+%Y-%m-%d %H:%M:%S'" in shell
    assert "date --iso-8601=seconds" not in shell

    assert "git pull --ff-only origin main" in powershell
    assert "VPS HEAD" in powershell
    assert "bash scripts/setup_market_discord_production.sh" in powershell
    assert "1566004926209990776" in powershell
