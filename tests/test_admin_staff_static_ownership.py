from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_admin_staff_owns_stable_stylesheet() -> None:
    template = (ROOT / "web/app/templates/admin_staff.html").read_text(encoding="utf-8")
    stable = ROOT / "web/app/static/css/pages/admin_staff.css"
    legacy = ROOT / "web/app/static/css/pages/admin_staff_inline_1.css"

    assert '/static/css/pages/admin_staff.css?v=20261013' in template
    assert "admin_staff_inline_1.css" not in template
    assert stable.is_file()
    assert not legacy.exists()
    assert ".member-grid" in stable.read_text(encoding="utf-8")
