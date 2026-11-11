"""Run the EXACT VPS pre-deploy Python scope guard in CI.

Regression for the old farm-enabled VPS: importing a pinned replacement module
before services.__init__ used to throw ImportError from services.order_rules.
The preflight must succeed *before stopping either service or touching DBs*.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO / "scripts/deploy_nov10_game_prices.sh"


def test_release_scope_guard_bootstraps_services_before_target_module():
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'^\./venv/bin/python - "\$OLD_HEAD" "\$TARGET" <<\'PY\'\n(.*?)\nPY$',
        source, flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "Scope-guard heredoc changed; test its exact new entry point"
    scope_guard = match.group(1)
    assert scope_guard.index("import services\n") < scope_guard.index(
        'sys.modules[farm_name]=farm_mod'
    )
    # HEAD vs HEAD proves the guard is independent of the deployed branch's
    # startup order. Stale command wrappers are not used; this is exactly the
    # same scope-guard Python program as the VPS shell deploy executes.
    proc = subprocess.run(
        [sys.executable, "-", "HEAD", "HEAD"],
        input=scope_guard, text=True,
        cwd=REPO,
        env={**os.environ, "WEB_SECRET_KEY": "deploy-scope-guard-ci-only"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=50, check=False,
    )
    assert proc.returncode == 0, (
        f"VPS preflight failed before deployment:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "PASS: every non-target game/order rule unchanged" in proc.stdout


def test_shell_release_script_has_valid_bash_syntax():
    proc = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
