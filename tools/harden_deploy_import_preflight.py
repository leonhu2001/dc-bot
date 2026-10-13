from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy_main.sh"
TEST = ROOT / "tests" / "test_deploy_runtime_import_preflight.py"

source = DEPLOY.read_text(encoding="utf-8")

source = source.replace(
    "NGINX_CONFIG_UPDATED=0\n",
    "NGINX_CONFIG_UPDATED=0\nSERVICES_RESTARTED=0\n",
    1,
)

source = source.replace(
    '''    if [ "$SOURCE_UPDATED" -eq 1 ]; then\n        restart_services || true\n\n        echo "Bot after rollback: $(systemctl is-active \"$BOT_SERVICE\" || true)"\n        echo "Web after rollback: $(systemctl is-active \"$WEB_SERVICE\" || true)"\n    fi\n''',
    '''    if [ "$SERVICES_RESTARTED" -eq 1 ]; then\n        restart_services || true\n\n        echo "Bot after rollback: $(systemctl is-active \"$BOT_SERVICE\" || true)"\n        echo "Web after rollback: $(systemctl is-active \"$WEB_SERVICE\" || true)"\n    fi\n''',
    1,
)

compile_anchor = '''echo "PASS: Python compile"\necho\n\necho "=== 6. ENSURE DATABASE TABLES ==="\n'''
preflight = '''echo "PASS: Python compile"\necho\n\necho "=== 5B. RUNTIME IMPORT PREFLIGHT ==="\n"$APP/venv/bin/python" -c "from services.payment_review_runtime import ensure_payment_review_worker_started"\necho "PASS: critical Bot runtime imports"\necho\n\necho "=== 6. ENSURE DATABASE TABLES ==="\n'''
if compile_anchor not in source:
    raise RuntimeError("compile/preflight anchor not found")
source = source.replace(compile_anchor, preflight, 1)

restart_anchor = '''echo "Web stop timeout: $(systemctl show "$WEB_SERVICE" -p TimeoutStopUSec --value 2>/dev/null || echo unknown)"\nrestart_services\n'''
restart_replacement = '''echo "Web stop timeout: $(systemctl show "$WEB_SERVICE" -p TimeoutStopUSec --value 2>/dev/null || echo unknown)"\nSERVICES_RESTARTED=1\nrestart_services\n'''
if restart_anchor not in source:
    raise RuntimeError("restart anchor not found")
source = source.replace(restart_anchor, restart_replacement, 1)

DEPLOY.write_text(source, encoding="utf-8")

TEST.write_text(
    '''from pathlib import Path\n\n\ndef test_deploy_import_preflight_runs_before_service_restart():\n    source = Path("scripts/deploy_main.sh").read_text(encoding="utf-8")\n    preflight = 'from services.payment_review_runtime import ensure_payment_review_worker_started'\n    assert preflight in source\n    assert source.index(preflight) < source.index('=== 8. RESTART SERVICES ===')\n\n\ndef test_pre_restart_failure_does_not_restart_healthy_services_during_rollback():\n    source = Path("scripts/deploy_main.sh").read_text(encoding="utf-8")\n    assert 'SERVICES_RESTARTED=0' in source\n    assert 'if [ "$SERVICES_RESTARTED" -eq 1 ]; then' in source\n    assert source.index('SERVICES_RESTARTED=1') > source.index('=== 8. RESTART SERVICES ===')\n''',
    encoding="utf-8",
)

print("deploy runtime import preflight hardened")
