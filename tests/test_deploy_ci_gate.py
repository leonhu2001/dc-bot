from pathlib import Path


def test_windows_deploy_blocks_before_remote_work_without_successful_main_ci():
    source = Path("scripts/deploy_main.ps1").read_text(encoding="utf-8")

    assert "=== VERIFY TARGET CI ===" in source
    assert "actions/runs?event=push&head_sha=$Target" in source
    assert '$_.head_branch -eq "main"' in source
    assert '$_.head_sha -eq $Target' in source
    assert '$CiRun.status -ne "completed"' in source
    assert '$CiRun.conclusion -ne "success"' in source
    assert "Deployment blocked" in source

    ci_gate_index = source.index("=== VERIFY TARGET CI ===")
    first_remote_work_index = source.index("=== SYNC ORDER PANEL IMAGES ===")
    assert ci_gate_index < first_remote_work_index


def test_ci_parses_windows_deploy_script():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate deploy PowerShell" in workflow
    assert "System.Management.Automation.Language.Parser" in workflow
    assert "scripts/deploy_main.ps1" in workflow
