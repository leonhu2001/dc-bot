from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_accounting_anomaly_inspector_runs_read_only_without_runtime_databases() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/inspect_accounting_anomalies.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ACCOUNTING RECONCILIATION DIAGNOSTIC (READ ONLY)" in completed.stdout
    assert "READ_ONLY: this script does not modify either database." in completed.stdout
