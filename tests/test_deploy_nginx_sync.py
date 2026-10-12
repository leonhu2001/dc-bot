from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = (ROOT / "scripts" / "deploy_main.sh").read_text(encoding="utf-8")
NGINX = (ROOT / "nginx_dc_bot_dashboard.conf").read_text(encoding="utf-8")


def test_deploy_validates_and_rolls_back_managed_nginx_config() -> None:
    assert "NGINX_CONFIG_UPDATED=0" in DEPLOY
    assert "nginx -t" in DEPLOY
    assert "systemctl reload nginx" in DEPLOY
    assert "Restoring previous Nginx config" in DEPLOY


def test_production_optional_pytest_does_not_require_browser_runtime() -> None:
    assert "--ignore=tests/e2e" in DEPLOY


def test_static_assets_have_compression_and_browser_cache_policy() -> None:
    assert "gzip on;" in NGINX
    assert "location /static/" in NGINX
    assert 'Cache-Control "public, max-age=604800"' in NGINX
