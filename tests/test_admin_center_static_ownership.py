from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_admin_center_owns_stable_stylesheet() -> None:
    template = (ROOT / "web/app/templates/admin_center.html").read_text(encoding="utf-8")
    stable = ROOT / "web/app/static/css/pages/admin_center.css"
    legacy = ROOT / "web/app/static/css/pages/admin_center_inline_1.css"

    assert '/static/css/pages/admin_center.css?v=' in template
    assert "admin_center_inline_1.css" not in template
    assert stable.is_file()
    assert not legacy.exists()
    assert ".center-grid" in stable.read_text(encoding="utf-8")
