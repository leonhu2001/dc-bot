from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_market_backup_keeps_credentials_out_of_pg_dump_arguments():
    text = (ROOT / "scripts" / "market_backup.py").read_text(encoding="utf-8")

    assert 'env["PGPASSWORD"]' in text
    assert '"--format=custom"' in text
    assert '"--no-owner"' in text
    assert '"--no-privileges"' in text
    assert '[pg_restore, "--list", str(temp_path)]' in text
    assert "MARKET_BACKUP_RETENTION_DAYS" in text
    assert "market_*.dump" in text
    assert "raw_url" not in "\n".join(
        line for line in text.splitlines() if "print(" in line
    )


def test_market_health_probe_requires_fresh_market_and_web_push():
    text = (ROOT / "scripts" / "market_health_probe.py").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000/health/market" in text
    assert "MARKET_HEALTH_REQUIRE_WEB_PUSH" in text
    assert 'payload.get("item_count")' in text
    assert 'payload.get("web_push_enabled")' in text
    assert "if not ok:" in text


def test_market_operations_units_schedule_backup_and_health_probe():
    backup_service = (ROOT / "dc-bot-market-backup.service").read_text(encoding="utf-8")
    backup_timer = (ROOT / "dc-bot-market-backup.timer").read_text(encoding="utf-8")
    health_service = (ROOT / "dc-bot-market-health.service").read_text(encoding="utf-8")
    health_timer = (ROOT / "dc-bot-market-health.timer").read_text(encoding="utf-8")

    assert "scripts/market_backup.py" in backup_service
    assert "ReadWritePaths=/opt/dc-bot/_archive/market_db" in backup_service
    assert "03:20:00 Asia/Taipei" in backup_timer
    assert "Persistent=true" in backup_timer
    assert "scripts/market_health_probe.py" in health_service
    assert "MARKET_HEALTH_REQUIRE_WEB_PUSH=1" in health_service
    assert "OnUnitActiveSec=5m" in health_timer


def test_market_operations_setup_installs_and_runs_both_checks():
    shell = (ROOT / "scripts" / "setup_market_operations.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts" / "setup_market_operations.ps1").read_text(encoding="utf-8")

    assert "pg_dump" in shell
    assert "pg_restore" in shell
    assert 'BACKUP_DIR="$APP/_archive/market_db"' in shell
    assert "systemctl enable --now" in shell
    assert 'systemctl start "$BACKUP_SERVICE"' in shell
    assert 'systemctl start "$HEALTH_SERVICE"' in shell
    assert "setup_web_push_production.ps1" in shell
    assert "git pull --ff-only origin main" in powershell
    assert "VPS HEAD" in powershell
    assert "bash scripts/setup_market_operations.sh" in powershell
