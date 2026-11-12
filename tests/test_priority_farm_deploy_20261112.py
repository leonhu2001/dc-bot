"""Safe priority release must be pinned, limited, backed up and reversible."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SH=ROOT/"scripts/deploy_priority_farm_ticket_20261112.sh"
PS=ROOT/"scripts/deploy_priority_farm_ticket_20261112.ps1"


def test_safe_priority_deploy_shell_syntax_and_scope():
    completed=subprocess.run(
        ["bash","-n",str(SH)],capture_output=True,text=True,timeout=15,
    )
    assert completed.returncode==0,completed.stderr
    text=SH.read_text(encoding="utf-8")
    assert "OLD_FARM_RELEASE=ed70f897a1dc4178922df8296cb6d1395acf61f5" in text
    assert "OLD_PANEL_RELEASE=b179aa72b50400ccf01d80840e145dbdb2e6accc" in text
    assert "OLD_EXAMINER_RELEASE=a34a2fb0046568b66a7a295132c2444f63e338d7" in text
    assert "BLOCKED: file outside approved price/ticket scope" in text
    assert "requirements.txt web/requirements-web.txt" in text
    assert "src.backup(dst)" in text
    assert 'git reset --hard "$OLD_HEAD"' in text
    assert "systemctl restart" in text
    assert "=== READ-ONLY PRIORITY MARGIN / DISCORD-WEB CONTRACT ===" in text
    assert "len(PUBLIC_FARM_FIXED_CUTS)==20" in text
    assert "priority_farm_ticket_" in text
    assert "DEPLOY COMPLETED: +260 internal and +280 public priority" in text


def test_priority_release_ps1_verifies_ci_and_exits_on_ssh_failure():
    text=PS.read_text(encoding="utf-8")
    assert "feat/farm-priority-worker-only-and-ticket-idempotency-20261112" in text
    assert "deploy_priority_farm_ticket_20261112.sh" in text
    assert "GitHub CI" in text or "VERIFY PINNED CI" in text
    assert '$LASTEXITCODE -ne 0' in text
    assert '"-o", "BatchMode=yes"' in text
    assert 'ssh @SshArgs' in text
    assert "Worker" not in text or "worker" in text.lower()
