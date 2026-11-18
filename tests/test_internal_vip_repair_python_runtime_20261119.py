"""Regression: repair audit must work without importing the live Bot/Web stack."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vip_repair_audit_bootstraps_without_site_packages(tmp_path):
    """-S removes third-party site packages: missing DB, not SQLAlchemy, must fail."""
    missing_db = tmp_path / "nonexistent-bot.db"
    script = ROOT / "scripts" / "repair_internal_staff_vip_20261119.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script), "--db", str(missing_db)],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 1
    assert "找不到 bot.db" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert not missing_db.exists()


def test_windows_wrapper_uses_production_venv_for_both_paths():
    wrapper = (ROOT / "scripts" / "repair_internal_staff_vip.ps1").read_text(
        encoding="utf-8"
    )
    assert "./venv/bin/python scripts/repair_internal_staff_vip_20261119.py --vip-only" in wrapper
    assert "bash scripts/repair_internal_staff_vip_remote.sh" in wrapper
    assert "python3 scripts/repair_internal_staff_vip_20261119.py" not in wrapper
    assert 'if (-not $Apply)' in wrapper
    assert "| & ssh" not in wrapper
    remote = (ROOT / "scripts" / "repair_internal_staff_vip_remote.sh").read_text(encoding="utf-8")
    assert "--vip-only --check-apply" in remote
    assert "--vip-only --apply" in remote
    assert "trap restore EXIT" in remote
