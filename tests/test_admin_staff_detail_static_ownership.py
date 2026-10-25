from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "web/app/templates/admin_staff_detail.html"
LEGACY_SCRIPT = ROOT / "web/app/static/js/pages/admin_staff_detail_inline_1.js"


def test_admin_staff_detail_has_no_dead_form_script() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="pf"' not in template
    assert 'id="vis"' not in template
    assert "admin_staff_detail_inline_1.js" not in template
    assert not LEGACY_SCRIPT.exists()
