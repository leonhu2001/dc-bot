from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = ROOT / "scripts" / "setup_web_push_production.sh"
SETUP_PS1 = ROOT / "scripts" / "setup_web_push_production.ps1"
MARKET_PUSH_ROUTER = ROOT / "web" / "app" / "routers" / "market_push.py"


def test_web_push_setup_keeps_private_key_on_vps_and_has_rollback():
    text = SETUP_SH.read_text(encoding="utf-8")

    assert "WEB_PUSH_VAPID_PRIVATE_KEY" in text
    assert "WEB_PUSH_VAPID_PUBLIC_KEY" in text
    assert "WEB_PUSH_VAPID_SUBJECT" in text
    assert "Vapid.from_string" in text
    assert "vapid.generate_keys()" in text
    assert 'private_value.to_bytes(32, "big")' in text
    assert "existing VAPID public/private keys do not match" in text
    assert "trap rollback ERR" in text
    assert "cp -a \"$BACKUP_DIR/web.env\" \"$ENV_FILE\"" in text
    assert 'systemctl restart "${services[@]}"' in text
    assert "WEB_PUSH_VAPID_PRIVATE_KEY=" not in text
    assert "print(private" not in text


def test_web_push_windows_launcher_requires_deployed_main_before_setup():
    text = SETUP_PS1.read_text(encoding="utf-8")

    assert "git pull --ff-only origin main" in text
    assert "git rev-parse HEAD" in text
    assert "VPS HEAD" in text
    assert "Run SAFE DEPLOY for this commit first" in text
    assert "bash scripts/setup_web_push_production.sh" in text


def test_market_health_is_dedicated_and_does_not_replace_core_health():
    text = MARKET_PUSH_ROUTER.read_text(encoding="utf-8")

    assert '@router.get("/health/market"' in text
    assert "status_code=200 if status.ok else 503" in text
    assert "check_market_health" in text
