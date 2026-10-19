from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy_main.sh"
SMOKE = ROOT / "tools" / "runtime_import_smoke.py"


def test_runtime_import_smoke_module_is_importable():
    module = importlib.import_module("tools.runtime_import_smoke")
    assert "cogs.wallet_commands" in module.CRITICAL_RUNTIME_MODULES
    assert "cogs.staff_profile_commands" in module.CRITICAL_RUNTIME_MODULES
    assert "services.payment_review_runtime" in module.CRITICAL_RUNTIME_MODULES
    assert "services.vip_voice_runtime" in module.CRITICAL_RUNTIME_MODULES
    assert "services.order_payment_composition" in module.CRITICAL_RUNTIME_MODULES
    assert "services.wallet_discord_runtime" in module.CRITICAL_RUNTIME_MODULES
    assert "views.review" in module.CRITICAL_RUNTIME_MODULES


def test_runtime_import_smoke_executes_all_critical_imports(capsys):
    module = importlib.import_module("tools.runtime_import_smoke")
    module.main()
    output = capsys.readouterr().out
    assert "PASS: imported" in output
    assert "validated" in output
    assert "bot import contracts" in output


def test_runtime_import_smoke_runs_as_deploy_invokes_it():
    result = subprocess.run(
        [sys.executable, str(SMOKE)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "PASS: imported" in result.stdout
    assert "bot import contracts" in result.stdout


def test_runtime_import_smoke_validates_bot_symbol_ownership():
    module = importlib.import_module("tools.runtime_import_smoke")
    count = module._validate_bot_import_contracts()
    assert count > 0


def test_wallet_compatibility_adapters_use_explicit_canonical_imports():
    module = importlib.import_module("tools.runtime_import_smoke")
    expected = {
        "_wallet_ensure_tables": (
            "services.wallet_service",
            "ensure_wallet_tables",
        ),
        "_wallet_get_balance": (
            "services.wallet_service",
            "get_wallet_balance",
        ),
        "adjust_customer_wallet_balance": (
            "services.wallet_discord_runtime",
            "adjust_customer_wallet_balance",
        ),
        "send_wallet_log": (
            "services.wallet_discord_runtime",
            "send_wallet_log",
        ),
    }
    for alias_name, owner in expected.items():
        assert module.REQUIRED_BOT_IMPORT_ALIASES[alias_name] == owner

    assert "_wallet_get_transactions" not in module.REQUIRED_BOT_IMPORT_ALIASES


def test_self_service_selection_imports_use_canonical_owner():
    module = importlib.import_module("tools.runtime_import_smoke")
    for symbol in (
        "_truncate_select_text",
        "get_specified_staff_entries_for_rule",
        "_acknowledge_component_interaction",
        "_edit_component_message",
        "SelfServiceSpecifiedStaffDropdown",
        "SelfServiceSpecifiedStaffPageButton",
        "SelfServiceSpecifiedStaffClearButton",
        "SelfServiceSpecifiedStaffDoneButton",
        "SelfServicePointBenefitSelect",
        "SelfServicePointBenefitView",
        "SelfServiceSpecifiedStaffDropdownView",
    ):
        assert module.REQUIRED_BOT_IMPORT_ALIASES[symbol] == (
            "services.self_service_selection_runtime",
            symbol,
        )


def test_deploy_runs_runtime_import_preflight_before_restart():
    source = DEPLOY.read_text(encoding="utf-8")
    preflight = '"$APP/venv/bin/python" "$APP/tools/runtime_import_smoke.py"'
    assert preflight in source
    assert source.index(preflight) < source.index('=== 8. RESTART SERVICES ===')


def test_pre_restart_failure_does_not_restart_healthy_services_on_rollback():
    source = DEPLOY.read_text(encoding="utf-8")
    assert "SERVICES_RESTARTED=0" in source
    assert 'if [ "$SERVICES_RESTARTED" -eq 1 ]; then' in source
