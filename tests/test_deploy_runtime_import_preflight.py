from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy_main.sh"
SMOKE = ROOT / "tools" / "runtime_import_smoke.py"


def test_runtime_import_smoke_module_is_importable():
    module = importlib.import_module("tools.runtime_import_smoke")
    assert "services.payment_review_runtime" in module.CRITICAL_RUNTIME_MODULES
    assert "services.vip_voice_runtime" in module.CRITICAL_RUNTIME_MODULES
    assert "views.review" in module.CRITICAL_RUNTIME_MODULES


def test_runtime_import_smoke_executes_all_critical_imports(capsys):
    module = importlib.import_module("tools.runtime_import_smoke")
    module.main()
    output = capsys.readouterr().out
    assert "PASS: imported" in output


def test_deploy_runs_runtime_import_preflight_before_restart():
    source = DEPLOY.read_text(encoding="utf-8")
    preflight = '"$APP/venv/bin/python" "$APP/tools/runtime_import_smoke.py"'
    assert preflight in source
    assert source.index(preflight) < source.index('=== 8. RESTART SERVICES ===')


def test_pre_restart_failure_does_not_restart_healthy_services_on_rollback():
    source = DEPLOY.read_text(encoding="utf-8")
    assert "SERVICES_RESTARTED=0" in source
    assert 'if [ "$SERVICES_RESTARTED" -eq 1 ]; then' in source
    assert source.index("SERVICES_RESTARTED=1") > source.index('=== 8. RESTART SERVICES ===')


def test_runtime_import_smoke_script_keeps_explicit_import_loop():
    source = SMOKE.read_text(encoding="utf-8")
    assert "importlib.import_module(module_name)" in source
