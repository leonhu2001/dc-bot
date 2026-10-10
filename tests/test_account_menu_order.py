from pathlib import Path


def test_wallet_link_is_moved_before_logout_section_even_if_it_already_exists():
    source = Path("web/app/static/js/mw_site.js").read_text(encoding="utf-8")

    assert 'const accountDropdown = document.querySelector(' in source
    assert "let walletLink = accountDropdown.querySelector(" in source
    assert "if (!walletLink)" in source
    assert "logoutLink.previousElementSibling" in source
    assert "accountDropdown.insertBefore(\n                walletLink,\n                logoutDivider" in source
    assert 'accountDropdown\n        && !accountDropdown.querySelector(' not in source
