import subprocess
import sys


def test_order_rules_audit_accepts_game_rank_only_receiver_rules():
    result = subprocess.run(
        [sys.executable, "tools/audit_order_rules.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ORDER_RULES_AUDIT_PASS" in result.stdout
    assert "valorant_ascendant_ng: allowed_roles is empty" not in result.stdout
