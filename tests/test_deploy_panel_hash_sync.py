from pathlib import Path


SCRIPT = Path("scripts/deploy_main.ps1")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_order_panel_deploy_compares_sha256_before_uploading() -> None:
    source = _source()

    assert "Get-FileHash -LiteralPath $PanelAssetPath -Algorithm SHA256" in source
    assert "$ChangedPanelAssets = @()" in source
    assert "sha256sum" in source
    assert "/opt/dc-bot/assets/order_panels/$($PanelAsset.Name)" in source
    assert "/opt/dc-bot/web/app/static/order_panels/$($PanelAsset.Name)" in source


def test_order_panel_deploy_skips_all_network_asset_work_when_unchanged() -> None:
    source = _source()

    assert 'if ($ChangedPanelAssets.Count -eq 0)' in source
    assert 'SKIP: order panel images unchanged' in source
    assert 'SKIP: no changed public panel images to verify' in source
    assert 'Uploading 5 public panel images' not in source


def test_order_panel_deploy_uploads_and_verifies_only_changed_assets() -> None:
    source = _source()

    assert "$ChangedPanelAssetPaths = @($ChangedPanelAssets | ForEach-Object { $_.Path })" in source
    assert '& scp @SshTransportArgs @ChangedPanelAssetPaths' in source
    assert 'foreach ($PanelAsset in $ChangedPanelAssets)' in source
    assert 'changed public panel image URLs are reachable' in source
