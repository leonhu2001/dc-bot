from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy_main.sh"


def _source() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def test_final_service_status_cannot_trigger_rollback_inside_command_substitution() -> None:
    source = _source()
    assert '$(systemctl is-active "$BOT_SERVICE")' not in source
    assert '$(systemctl is-active "$WEB_SERVICE")' not in source
    assert 'get_service_state()' in source
    assert 'systemctl is-active "$service" 2>/dev/null || true' in source


def test_deploy_requires_stable_services_before_writing_success_marker() -> None:
    source = _source()
    stability = source.index('=== 10. FINAL STABILITY CHECK ===')
    marker = source.index('=== 11. WRITE DEPLOYMENT MARKER ===')
    success = source.index('SAFE DEPLOY SUCCESS')
    assert stability < marker < success
    assert 'verify_service_stability "$BOT_SERVICE" "Bot"' in source
    assert 'verify_service_stability "$WEB_SERVICE" "Web"' in source


def test_stability_check_detects_restart_or_non_active_state() -> None:
    source = _source()
    assert 'get_service_restart_count()' in source
    assert 'current_restarts > baseline_restarts' in source
    assert 'if [ "$state" != "active" ]; then' in source
    assert 'journalctl -u "$service" -n 100 --no-pager' in source


def test_runtime_marker_is_backed_up_and_reconciled_on_rollback() -> None:
    source = _source()
    assert 'MARKER_PATH="$APP/data/deployed_version.json"' in source
    assert 'MARKER_UPDATED=0' in source
    assert 'MARKER_EXISTED=0' in source
    assert 'cp -L "$MARKER_PATH" "$BACKUP/deployed_version.json"' in source
    assert '"rolled_back"' in source
    assert '"$OLD_HEAD"' in source
    assert '"$TARGET"' in source
    assert 'PASS: deployment marker reconciled to rollback source' in source
    assert 'restoring previous marker backup' in source


def test_source_mismatch_after_reset_uses_transactional_failure_path() -> None:
    source = _source()
    mismatch_block = source.split('if [ "$(git rev-parse HEAD)" != "$TARGET" ]; then', 1)[1].split("fi", 1)[0]
    assert "false" in mismatch_block
    assert "exit 1" not in mismatch_block


def test_success_banner_only_runs_after_err_trap_is_disabled() -> None:
    source = _source()
    trap_off = source.rindex("trap - ERR")
    success = source.index('SAFE DEPLOY SUCCESS')
    assert trap_off < success
