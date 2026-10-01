import os
import sqlite3
import time

from web.app.services import system_health


def test_parse_key_value_lines():
    parsed = system_health._parse_key_value_lines(
        "ActiveState=active\nSubState=running\nMainPID=123\n"
    )

    assert parsed["ActiveState"] == "active"
    assert parsed["SubState"] == "running"
    assert parsed["MainPID"] == "123"


def test_inspect_database_runs_quick_check_and_counts(tmp_path):
    db_path = tmp_path / "web_dashboard.db"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE payment_reviews (
                id INTEGER PRIMARY KEY,
                status TEXT
            );

            CREATE TABLE sync_events (
                id INTEGER PRIMARY KEY,
                status TEXT
            );

            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT
            );

            INSERT INTO payment_reviews(status)
            VALUES
                ('pending_review'),
                ('approved_pending_apply'),
                ('apply_error');

            INSERT INTO sync_events(status)
            VALUES
                ('failed'),
                ('pending');

            INSERT INTO web_orders(status)
            VALUES
                ('active'),
                ('closed');
            """
        )
        conn.commit()

    snapshot = system_health.inspect_database(
        db_path,
        system_health.WEB_DB_CHECKS,
        label="Web 資料庫",
    )

    assert snapshot["ok"] is True
    assert snapshot["integrity"] == "正常"
    assert snapshot["metrics"]["payment_pending"] == 2
    assert snapshot["metrics"]["payment_apply_error"] == 1
    assert snapshot["metrics"]["sync_failed"] == 1
    assert snapshot["metrics"]["sync_backlog"] == 1
    assert snapshot["metrics"]["open_orders"] == 1


def test_inspect_database_missing_file_is_safe(tmp_path):
    snapshot = system_health.inspect_database(
        tmp_path / "missing.db",
        system_health.WEB_DB_CHECKS,
        label="Missing",
    )

    assert snapshot["exists"] is False
    assert snapshot["ok"] is False
    assert snapshot["integrity"] == "無法檢查"


def test_inspect_backups_picks_newest_database_files(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    old_bot = backups_dir / "bot_older.db"
    new_bot = backups_dir / "bot_newer.db"
    web_backup = backups_dir / "web_dashboard_20261002.db"

    for path in (old_bot, new_bot, web_backup):
        path.write_bytes(b"sqlite-placeholder")

    now = time.time()
    os.utime(old_bot, (now - 7200, now - 7200))
    os.utime(new_bot, (now - 3600, now - 3600))
    os.utime(web_backup, (now - 1800, now - 1800))

    snapshot = system_health.inspect_backups(tmp_path)

    assert snapshot["bot"]["found"] is True
    assert snapshot["bot"]["path"] == "backups/bot_newer.db"
    assert snapshot["bot"]["fresh"] is True

    assert snapshot["web_dashboard"]["found"] is True
    assert snapshot["web_dashboard"]["path"] == "backups/web_dashboard_20261002.db"
    assert snapshot["web_dashboard"]["fresh"] is True


def test_inspect_service_fails_closed_when_systemctl_unavailable(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "_run_command",
        lambda *args, **kwargs: {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "error": "PermissionError",
        },
    )

    snapshot = system_health.inspect_service("dc-bot.service")

    assert snapshot["available"] is False
    assert snapshot["ok"] is False
    assert snapshot["status_text"] == "無法取得"

def test_inspect_git_uses_deployment_marker_when_git_is_unavailable(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "deployed_version.json").write_text(
        """
{
  "commit": "1234567890abcdef1234567890abcdef12345678",
  "branch": "main",
  "deployed_at": "2026-10-02T00:30:00+08:00",
  "subject": "Test deploy marker",
  "status": "success"
}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        system_health,
        "_run_command",
        lambda *args, **kwargs: {
            "ok": False,
            "returncode": 128,
            "stdout": "",
            "error": "git unavailable",
        },
    )

    snapshot = system_health.inspect_git(tmp_path)

    assert snapshot["available"] is True
    assert snapshot["commit"] == "1234567890ab"
    assert snapshot["branch"] == "main"
    assert snapshot["subject"] == "Test deploy marker"
    assert snapshot["source"] == "deployment_marker"
    assert snapshot["dirty"] is None

