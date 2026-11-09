"""Check the price-isolated deploy path instead of weakening deploy_main."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_isolated_bash_deployment_syntax_and_baseline_guards():
    shell = ROOT / "scripts" / "deploy_payment_only.sh"
    subprocess.run(["bash", "-n", str(shell)], check=True)
    source = shell.read_text(encoding="utf-8")
    assert 'BASE="d637f16412d15bb8bc77229d105c7816b35da06d"' in source
    assert '[[ "$OLD" == "$BASE" ]]' in source
    assert "price" in source.lower()
    assert "git switch --detach" in source
    assert "systemctl" in source
    assert "rollback()" in source
    for path in ("cathay_qr.jpg", "jkopay_qr.jpg"):
        assert path in source


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_isolated_powershell_scripts_parse():
    for name in ("deploy_payment_only.ps1", "sync_payment_qr_images.ps1"):
        path = ROOT / "scripts" / name
        code = (
            "$tokens=$null; $errors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{str(path).replace(chr(39), chr(39) + chr(39))}',"
            "[ref]$tokens,[ref]$errors) | Out-Null;"
            "if($errors.Count -gt 0) {"
            "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        subprocess.run(["pwsh", "-NoProfile", "-Command", code], check=True)
