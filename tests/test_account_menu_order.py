from pathlib import Path


def test_wallet_link_is_inserted_before_logout_section():
    source = Path("web/app/static/js/mw_site.js").read_text(encoding="utf-8")

    assert '[href="/auth/logout"]' in source
    assert "logoutLink.previousElementSibling" in source
    assert 'logoutDivider.classList.contains(\n                "account-divider"' in source
    assert "accountDropdown.insertBefore(\n                walletLink,\n                logoutDivider" in source
