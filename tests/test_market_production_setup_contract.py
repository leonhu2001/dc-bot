from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_market_service_follows_web_restart_lifecycle():
    text = (_repo_root() / "dc-bot-market.service").read_text(encoding="utf-8")
    assert "PartOf=dc-bot-dashboard.service" in text
    assert "ExecStart=/opt/dc-bot/venv/bin/python -m services.market.worker" in text


def test_market_production_setup_uses_verified_tw_provider_and_isolated_db():
    text = (_repo_root() / "scripts" / "setup_market_production.sh").read_text(
        encoding="utf-8"
    )

    assert 'DB_NAME="${MARKET_DB_NAME:-mowan_market}"' in text
    assert 'DB_ROLE="${MARKET_DB_ROLE:-mowan_market}"' in text
    assert '"MARKET_PROVIDER": "852941-tw"' in text
    assert '"MARKET_852941_BASE_URL": "https://app.852941.xyz"' in text
    assert '"MARKET_POLL_SECONDS": "900"' in text
    assert "run_market_cycle(" in text
    assert 'systemctl restart "$WEB_SERVICE" "$MARKET_SERVICE"' in text


def test_windows_market_setup_requires_deployed_head_to_match_main():
    text = (_repo_root() / "scripts" / "setup_market_production.ps1").read_text(
        encoding="utf-8"
    )

    assert "git pull --ff-only origin main" in text
    assert "VPS HEAD" in text
    assert "does not match local main" in text
    assert "bash scripts/setup_market_production.sh" in text
