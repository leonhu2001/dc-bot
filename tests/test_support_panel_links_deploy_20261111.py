"""Isolated panel links release safety and Discord edit-in-place contract."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_support_panel_links_20261111.sh"
WRAPPER = ROOT / "scripts/deploy_support_panel_links_20261111.ps1"


def test_support_panel_release_bash_is_valid_and_scope_is_narrow():
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)], cwd=ROOT,
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = SCRIPT.read_text(encoding="utf-8")
    assert "PREVIOUS_RELEASE=ed70f897a1dc4178922df8296cb6d1395acf61f5" in text
    assert "PREVIOUS_PANEL_RELEASE=b179aa72b50400ccf01d80840e145dbdb2e6accc" in text
    assert "tests/test_recruit_examiner_panel_permissions_20261111.py" in text
    assert 'guild_roles=request("GET","/guilds/1129474191226306672/roles")' in text
    assert "views/panels.py" in text
    assert "tests/test_main_service_panel.py" in text
    assert "tests/test_support_panel_links_deploy_20261111.py" in text
    assert "BLOCKED: unauthorized file modified" in text
    assert 'systemctl restart "$BOT_SERVICE"' in text
    assert "WEB AND DATABASES UNTOUCHED" in text
    assert "git reset --hard" in text
    assert 'request("PATCH",path,{"embeds":[embed]})' in text
    assert 'button_ids(after)!=expected_buttons' in text
    assert 'after["embeds"][0].get("description")!=description' in text
    assert "DEPLOY COMPLETED: order notice link and examiner access installed" in text


def test_support_panel_release_uses_original_existing_discord_message_and_no_new_post():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'channel_id="1497622678138519572"' in text
    assert 'message_id="1537533276884045856"' in text
    assert 'path=f"/channels/{channel_id}/messages/{message_id}"' in text
    assert 'request("GET",path)' in text
    assert 'request("PATCH",path,{"embeds":[embed]})' in text
    assert 'request("POST",path' not in text
    assert "DISCORD_TOKEN" in text
    assert "token)" not in text


def test_windows_wrapper_targets_isolated_release_and_requires_matching_ci():
    text = WRAPPER.read_text(encoding="utf-8")
    assert 'fix/support-panel-order-guide-recruit-examiner-20261111' in text
    assert 'deploy_support_panel_links_20261111.sh' in text
    assert '$_' not in text or 'error' in text.lower()
    assert '$Run.conclusion -ne "success"' in text
    assert 'ssh @SshArgs' in text
