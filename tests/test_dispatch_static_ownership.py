from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_dispatch_owns_stable_base_stylesheet() -> None:
    template = (ROOT / "web/app/templates/dispatch.html").read_text(encoding="utf-8")
    stable = ROOT / "web/app/static/css/pages/dispatch.css"
    legacy = ROOT / "web/app/static/css/pages/dispatch_inline_1.css"

    assert '/static/css/pages/dispatch.css?v=20261017-actions-2' in template
    assert "dispatch_inline_1.css" not in template
    assert stable.is_file()
    assert not legacy.exists()
    assert ".dispatch-shell" in stable.read_text(encoding="utf-8")
