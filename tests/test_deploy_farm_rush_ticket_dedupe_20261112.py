"""Read-only release contract for rush/duplicate-panel deployment scripts."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SH=ROOT/"scripts/deploy_farm_rush_ticket_dedupe_20261112.sh"
PS=ROOT/"scripts/deploy_farm_rush_ticket_dedupe_20261112.ps1"


def test_shell_deploy_is_parseable_and_checks_payouts_before_restart():
    proc=subprocess.run(["bash","-n",str(SH)],capture_output=True,text=True,timeout=10)
    assert proc.returncode==0,proc.stderr
    c=SH.read_text(encoding="utf-8")
    assert "fix/quick-ticket-duplicate-and-farm-rush-fees-20261112" in c
    assert "a34a2fb0046568b66a7a295132c2444f63e338d7" in c
    assert "ed70f897a1dc4178922df8296cb6d1395acf61f5" in c
    assert "=== ALLOWLIST CHANGE SCOPE ===" in c
    assert "BLOCKED: unauthorized changed path" in c
    assert "=== SAFE SQLITE BACKUPS ===" in c
    assert 'connection.backup(backup)' in c
    assert 'git reset --hard "$OLD_HEAD"' in c
    assert "=== READ-ONLY PRICE, PAYROLL AND CATALOG CHECKS ===" in c
    assert "assert len(PUBLIC_FARM_FIXED_CUTS)==20" in c
    assert "assert rush.worker_amount==normal.worker_amount+280" in c
    assert "staff_internal_ammo_dump_500m_rush" in c
    assert "staff_internal_car_500m_rush" in c
    assert "=== RESTART BOT + WEB ===" in c
    assert c.index("READ-ONLY PRICE")<c.index("=== RESTART BOT + WEB ===")
    assert "systemctl restart" in c
    assert "http://127.0.0.1:8000/health" in c
    assert "DEPLOY COMPLETED: duplicate self-service panel guarded" in c


def test_windows_wrapper_pins_exact_ci_and_target_before_ssh():
    c=PS.read_text(encoding="utf-8")
    assert "fix/quick-ticket-duplicate-and-farm-rush-fees-20261112" in c
    assert "deploy_farm_rush_ticket_dedupe_20261112.sh" in c
    assert ' $Run.conclusion -ne "success"' in c
    assert '"origin/$ReleaseRef"' in c
    assert "git switch -C" in c
    assert "& ssh @SshArgs" in c


def test_deploy_never_writes_historical_order_and_wage_tables():
    c=SH.read_text(encoding="utf-8")
    assert "DELETE FROM" not in c
    assert "UPDATE worker_payout" not in c
    assert "UPDATE web_orders" not in c
    assert "sqlite3.connect(dest)" in c
